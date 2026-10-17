"""Agendar etapa: distribui as tarefas de um projeto/etapa nos horários de estudo.

Ex.: seg/qua/sex às 19:00, sessões de 60 min -> as tarefas (na ordem do plano) são
encaixadas uma após a outra, respeitando a duração de cada uma e o que já está na agenda.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from app.models import Item, Projeto, StatusItem
from app.services import recorrencia
from app.services.progresso import Arvore, chave_irmaos

DURACAO_PADRAO = 30  # min, para tarefas sem duração estimada
MAX_SESSOES = 120  # proteção: no máximo ~120 sessões à frente


@dataclass
class Horarios:
	dias: list[str]  # ["MO", "WE", "FR"]
	hora: time
	minutos: int

	@classmethod
	def de_projeto(cls, p: Projeto) -> "Horarios | None":
		if not (p.agenda_dias and p.agenda_hora and p.agenda_minutos):
			return None
		return cls(p.agenda_dias.split(","), time.fromisoformat(p.agenda_hora), p.agenda_minutos)

	def texto(self) -> str:
		dias = ", ".join(recorrencia.DIAS_NOME[d] for d in recorrencia.DIAS if d in self.dias)
		return f"{dias} às {self.hora:%H:%M} ({self.minutos} min)"


@dataclass
class Encaixe:
	item: Item
	inicio: datetime
	fim: datetime
	caminho: str  # etapa dentro do projeto (ex.: "Leitura"), vazio se for item direto
	estourou: bool = False  # tarefa maior que a sessão


@dataclass
class Agendamento:
	horarios: Horarios
	encaixes: list[Encaixe] = field(default_factory=list)
	sobras: list[Item] = field(default_factory=list)  # não couberam no horizonte
	avisos: list[str] = field(default_factory=list)

	def por_dia(self) -> list[tuple[date, list[Encaixe]]]:
		dias: dict[date, list[Encaixe]] = {}
		for e in self.encaixes:
			dias.setdefault(e.inicio.date(), []).append(e)
		return sorted(dias.items())


def horarios_herdados(session: Session, projeto_id: int) -> tuple[Horarios | None, int]:
	"""Horários do próprio projeto ou do ancestral mais próximo; devolve também onde guardar.
	Guarda no projeto-pai (o "plano") quando existir, para as próximas etapas herdarem."""
	arv = Arvore.carregar(session)
	cam = arv.caminho(projeto_id)
	for p in reversed(cam):
		h = Horarios.de_projeto(p)
		if h:
			return h, p.id
	destino = cam[-2].id if len(cam) >= 2 else projeto_id
	return None, destino


def _tarefas(
	session: Session, projeto_id: int, remarcar: bool, agora: datetime, empurrar: bool = False
) -> list[tuple[Item, str]]:
	"""Tarefas a agendar, em ordem de árvore: itens do projeto e depois de cada subetapa
	(etapas travadas por um pai sequencial ficam de fora).
	- sempre: as sem data;  - remarcar: + as atrasadas;  - empurrar: + as já marcadas no futuro
	  (tudo é redistribuído na ordem do plano, "empurrando" as seguintes)."""
	arv = Arvore.carregar(session)
	travados = arv.bloqueados()  # num plano sequencial, só a etapa liberada entra
	abertos = (StatusItem.a_fazer, StatusItem.em_andamento)
	saida: list[tuple[Item, str]] = []

	def visitar(pid: int, rotulo: str):
		if pid in travados and pid != projeto_id:
			return
		itens = session.exec(select(Item).where(Item.projeto_id == pid, Item.recorrencia.is_(None))).all()
		for it in sorted(itens, key=chave_irmaos):
			if it.status not in abertos:
				continue
			sem_data = it.inicio is None
			atrasado = it.inicio is not None and it.inicio < agora
			futuro = it.inicio is not None and it.inicio >= agora
			if sem_data or ((remarcar or empurrar) and atrasado) or (empurrar and futuro):
				saida.append((it, rotulo))
		for f in arv.filhos.get(pid, []):
			visitar(f.id, f"{rotulo} › {f.nome}" if rotulo else f.nome)

	visitar(projeto_id, "")
	return saida


def _ocupados(session: Session, dia: date, ignorar: set[int]) -> list[tuple[datetime, datetime]]:
	"""Intervalos já tomados na agenda do dia (itens com horário), exceto os que serão movidos."""
	from app.routers.agenda import montar_agenda  # evita import circular

	res = []
	for e in montar_agenda(session, dia, dia):
		if e.item_id in ignorar or e.dia_inteiro or not e.inicio or e.tipo_entrada != "agendado":
			continue
		if e.status in ("concluido", "pulado", "cancelado"):
			continue
		fim = e.fim or e.inicio + timedelta(minutes=e.duracao_min or DURACAO_PADRAO)
		res.append((e.inicio, fim))
	return sorted(res)


def planejar(
	session: Session,
	projeto_id: int,
	horarios: Horarios,
	a_partir: date | None = None,
	remarcar: bool = True,
	agora: datetime | None = None,
	empurrar: bool = False,
	so_itens: set[int] | None = None,
	desde_item: int | None = None,
) -> Agendamento:
	"""`so_itens`: agenda só essas tarefas (ex.: remarcar uma).
	`desde_item`: com `empurrar`, só a tarefa informada e as que vêm depois dela no plano."""
	agora = agora or datetime.now()
	a_partir = max(a_partir or agora.date(), agora.date())
	ag = Agendamento(horarios)
	if not horarios.dias:
		ag.avisos.append("escolha pelo menos um dia da semana")
		return ag
	tarefas = _tarefas(session, projeto_id, remarcar, agora, empurrar)
	if so_itens is not None:
		tarefas = [t for t in tarefas if t[0].id in so_itens]
	if desde_item is not None:
		ids = [t[0].id for t in tarefas]
		tarefas = tarefas[ids.index(desde_item):] if desde_item in ids else []
	if not tarefas:
		ag.avisos.append("nenhuma tarefa em aberto para agendar (sem data" + (" ou atrasada" if remarcar else "") + ")")
		return ag
	movidas = {it.id for it, _ in tarefas}
	dias_idx = {recorrencia.DIAS.index(d) for d in horarios.dias if d in recorrencia.DIAS}
	fila = list(tarefas)
	dia = a_partir
	sessoes = 0
	while fila and sessoes < MAX_SESSOES:
		if dia.weekday() in dias_idx:
			ini = datetime.combine(dia, horarios.hora)
			fim_sessao = ini + timedelta(minutes=horarios.minutos)
			if fim_sessao > agora:  # sessão de hoje que já passou não conta
				sessoes += 1
				cursor = max(ini, agora.replace(second=0, microsecond=0))
				ocupados = _ocupados(session, dia, movidas)
				while fila:
					item, rotulo = fila[0]
					dur = timedelta(minutes=item.duracao_min or DURACAO_PADRAO)
					for o_ini, o_fim in ocupados:  # pula o que já está marcado
						if o_ini < cursor + dur and o_fim > cursor:
							cursor = max(cursor, o_fim)
					sessao_vazia = cursor == max(ini, agora.replace(second=0, microsecond=0))
					if cursor + dur <= fim_sessao:
						ag.encaixes.append(Encaixe(item, cursor, cursor + dur, rotulo))
						cursor += dur
						fila.pop(0)
					elif sessao_vazia and dur > timedelta(minutes=horarios.minutos):
						# tarefa maior que a sessão: ocupa a sessão inteira e passa do horário
						ag.encaixes.append(Encaixe(item, cursor, cursor + dur, rotulo, estourou=True))
						fila.pop(0)
						break
					else:
						break
		dia += timedelta(days=1)
	ag.sobras = [it for it, _ in fila]
	if ag.sobras:
		ag.avisos.append(f"{len(ag.sobras)} tarefa(s) não couberam nas próximas {MAX_SESSOES} sessões")
	sem_duracao = sum(1 for it, _ in tarefas if not it.duracao_min)
	if sem_duracao:
		ag.avisos.append(f"{sem_duracao} tarefa(s) sem duração estimada: considerei {DURACAO_PADRAO} min cada")
	return ag


def aplicar(session: Session, projeto_id: int, ag: Agendamento, guardar_em: int | None = None) -> int:
	"""Grava os horários nos itens e guarda os horários de estudo no projeto (para reutilizar)."""
	for e in ag.encaixes:
		e.item.inicio, e.item.fim, e.item.dia_inteiro = e.inicio, e.fim, False
		e.item.atualizado_em = datetime.now()
	destino = session.get(Projeto, guardar_em or projeto_id)
	if destino:
		destino.agenda_dias = ",".join(d for d in recorrencia.DIAS if d in ag.horarios.dias)
		destino.agenda_hora = ag.horarios.hora.strftime("%H:%M")
		destino.agenda_minutos = ag.horarios.minutos
	session.commit()
	return len(ag.encaixes)


def desagendar(session: Session, projeto_id: int, agora: datetime | None = None) -> int:
	"""Tira a data das tarefas em aberto do projeto/etapa que estão de hoje em diante
	(voltam para "sem data"). Tarefas concluídas e o passado ficam como estão."""
	agora = agora or datetime.now()
	arv = Arvore.carregar(session)
	ids = {projeto_id} | arv.descendentes(projeto_id)
	n = 0
	for it in session.exec(select(Item).where(Item.projeto_id.in_(ids), Item.recorrencia.is_(None))).all():
		if it.status in (StatusItem.a_fazer, StatusItem.em_andamento) and it.inicio and it.inicio.date() >= agora.date():
			it.inicio = it.fim = None
			it.dia_inteiro = False
			n += 1
	session.commit()
	return n


def proxima_para_agendar(session: Session, projeto_id: int) -> Projeto | None:
	"""Num projeto sequencial com horários guardados: a etapa liberada que ainda tem
	tarefas sem data (para sugerir "agendar")."""
	proj = session.get(Projeto, projeto_id)
	if not proj or not proj.sequencial or not Horarios.de_projeto(proj):
		return None
	arv = Arvore.carregar(session)
	travados = arv.bloqueados()
	for f in arv.filhos.get(projeto_id, []):
		if f.id in travados or arv.concluido(f.id):
			continue
		if _tarefas(session, f.id, remarcar=False, agora=datetime.now()):
			return f
		return None
	return None


# ---------------------------------------------------------------------------
# Agendar sozinho a próxima etapa (planos sequenciais com agenda_auto)
# ---------------------------------------------------------------------------
_AVISOS: list[str] = []  # avisos para a interface (app de um usuário só: memória do processo basta)


def avisar(texto: str) -> None:
	_AVISOS.append(texto)


def consumir_avisos() -> list[str]:
	avisos = _AVISOS[:]
	_AVISOS.clear()
	return avisos


def ao_concluir(session: Session, item: Item) -> list[str]:
	"""Chamado quando uma tarefa é concluída. Se isso completou uma etapa de um plano
	sequencial com "agendar sozinho", agenda a etapa seguinte nos horários do plano."""
	if not item.projeto_id or item.status != StatusItem.concluido:
		return []
	arv = Arvore.carregar(session)
	cam = arv.caminho(item.projeto_id)  # raiz ... etapa do item
	avisos = []
	for i, plano in enumerate(cam[:-1] if len(cam) > 1 else []):
		etapa = cam[i + 1]  # filho do plano no caminho do item
		if not (plano.sequencial and plano.agenda_auto and plano.status == "ativo"):
			continue
		horarios = Horarios.de_projeto(plano)
		if not horarios or not arv.concluido(etapa.id):
			continue
		proxima = proxima_para_agendar(session, plano.id)
		if proxima is None:
			continue
		ag = planejar(session, proxima.id, horarios, remarcar=False)
		if not ag.encaixes:
			avisos.append(f"{plano.nome}: {proxima.nome} liberada, mas não encontrei horário livre para agendar")
			continue
		primeiro = ag.encaixes[0].inicio
		aplicar(session, proxima.id, ag, guardar_em=plano.id)
		dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
		avisos.append(
			f"{plano.nome}: {proxima.nome} agendada sozinha — {len(ag.encaixes)} tarefa(s) "
			f"a partir de {dias[primeiro.weekday()]} {primeiro:%d/%m} às {primeiro:%H:%M}"
		)
		arv = Arvore.carregar(session)  # o banco mudou
	_AVISOS.extend(avisos)
	return avisos
