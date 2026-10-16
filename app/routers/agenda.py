"""Visões de agenda: intervalo de dias e o resumo de hoje (usado pelo espelho)."""
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, or_, select

from app.db import get_session
from app.models import Area, Item, Ocorrencia, Projeto, StatusItem
from app.routers.common import item_out
from app.schemas import Entrada, Hoje
from app.services import recorrencia
from app.services.progresso import Arvore, percentual

router = APIRouter(prefix="/api", tags=["agenda"])

MAX_DIAS = 400


def _caminho(projetos: dict, projeto_id: int | None) -> str | None:
	nomes, visto = [], set()
	while projeto_id in projetos and projeto_id not in visto:
		visto.add(projeto_id)
		nomes.append(projetos[projeto_id].nome)
		projeto_id = projetos[projeto_id].pai_id
	return " › ".join(reversed(nomes)) or None


def _entrada(item: Item, tipo: str, dia: date, inicio, fim, status: str, areas, projetos, session) -> Entrada:
	area = areas[item.area_id]
	projeto = projetos.get(item.projeto_id)
	return Entrada(
		tipo_entrada=tipo,
		item_id=item.id,
		titulo=item.titulo,
		tipo=item.tipo,
		data=dia,
		inicio=inicio,
		fim=fim,
		dia_inteiro=item.dia_inteiro,
		prioridade=item.prioridade,
		status=status,
		recorrente=bool(item.recorrencia),
		area_id=area.id,
		area_nome=area.nome,
		area_cor=area.cor,
		projeto_id=projeto.id if projeto else None,
		projeto_nome=projeto.nome if projeto else None,
		projeto_caminho=_caminho(projetos, item.projeto_id),
		duracao_min=item.duracao_min,
		progresso=percentual(item, session),
	)


def montar_agenda(session: Session, de: date, ate: date) -> list[Entrada]:
	if ate < de:
		raise HTTPException(422, "'ate' não pode ser antes de 'de'")
	if (ate - de).days > MAX_DIAS:
		raise HTTPException(422, f"intervalo máximo: {MAX_DIAS} dias")
	ini_dt, fim_dt = datetime.combine(de, time.min), datetime.combine(ate, time.max)
	areas = {a.id: a for a in session.exec(select(Area)).all()}
	projetos = {p.id: p for p in session.exec(select(Projeto)).all()}
	entradas: list[Entrada] = []

	# 1. Itens únicos agendados no intervalo
	unicos = session.exec(
		select(Item).where(Item.recorrencia.is_(None), Item.inicio >= ini_dt, Item.inicio <= fim_dt, Item.status != StatusItem.cancelado)
	).all()
	for it in unicos:
		entradas.append(_entrada(it, "agendado", it.inicio.date(), it.inicio, it.fim, it.status.value, areas, projetos, session))

	# 2. Itens recorrentes: expande a RRULE e cruza com o registro de ocorrências
	recorrentes = session.exec(
		select(Item).where(Item.recorrencia.is_not(None), Item.inicio <= fim_dt, Item.status != StatusItem.cancelado)
	).all()
	for it in recorrentes:
		registros = {
			o.data: o.status.value
			for o in session.exec(select(Ocorrencia).where(Ocorrencia.item_id == it.id, Ocorrencia.data >= de, Ocorrencia.data <= ate))
		}
		dur = recorrencia.duracao(it.inicio, it.fim)
		for quando in recorrencia.ocorrencias(it.recorrencia, it.inicio, de, ate):
			status = registros.get(quando.date(), "a_fazer")
			entradas.append(_entrada(it, "agendado", quando.date(), quando, quando + dur if dur else None, status, areas, projetos, session))

	# 3. Prazos que vencem no intervalo (itens não concluídos)
	prazos = session.exec(
		select(Item).where(
			Item.prazo >= ini_dt,
			Item.prazo <= fim_dt,
			Item.status.not_in([StatusItem.concluido, StatusItem.cancelado]),
		)
	).all()
	for it in prazos:
		entradas.append(_entrada(it, "prazo", it.prazo.date(), it.prazo, None, it.status.value, areas, projetos, session))

	# Ordena: dia → dia inteiro primeiro → horário → prioridade (crítica antes)
	entradas.sort(key=lambda e: (e.data, not e.dia_inteiro, e.inicio or datetime.min, -e.prioridade.peso))
	return entradas


@router.get("/agenda", response_model=list[Entrada])
def agenda(de: date, ate: date, session: Session = Depends(get_session)):
	"""Entradas entre `de` e `ate` (inclusive): agendados, ocorrências e prazos."""
	return montar_agenda(session, de, ate)


@router.get("/hoje", response_model=Hoje)
def hoje(dia: date | None = None, session: Session = Depends(get_session)):
	"""Resumo do dia: agenda de hoje, atrasados e pendências sem data."""
	dia = dia or date.today()
	abertos = [StatusItem.a_fazer, StatusItem.em_andamento]
	atrasados = session.exec(
		select(Item).where(
			Item.recorrencia.is_(None),
			Item.status.in_(abertos),
			or_(Item.inicio < datetime.combine(dia, time.min), Item.prazo < datetime.combine(dia, time.min)),
		)
	).all()
	# Pendências: sem data, abertas e fora de etapas travadas ou projetos pausados/arquivados
	fora = Arvore.carregar(session).fora_de_foco()
	pendencias = [
		i
		for i in session.exec(select(Item).where(Item.inicio.is_(None), Item.recorrencia.is_(None), Item.status.in_(abertos))).all()
		if i.projeto_id not in fora
	]
	ordem = lambda i: (-i.prioridade.peso, i.prazo or datetime.max)  # noqa: E731
	return Hoje(
		data=dia,
		agenda=montar_agenda(session, dia, dia),
		atrasados=[item_out(session, i) for i in sorted(atrasados, key=ordem)],
		pendencias=[item_out(session, i) for i in sorted(pendencias, key=ordem) if i not in atrasados],
	)
