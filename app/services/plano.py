"""Planejamento em Markdown (Obsidian) -> projetos e itens do app.

Uma única especificação (FORMATO) alimenta o modelo, os prompts para IA e o leitor,
para os três nunca ficarem diferentes entre si.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from app.services import duracao
from app.models import Area, Item, Link, Prioridade, ProgressoModo, Projeto, StatusItem, TipoItem

# ---------------------------------------------------------------------------
# Especificação (usada no modelo, nos prompts e na tela de importar)
# ---------------------------------------------------------------------------
FORMATO = """\
FORMATO DO PLANEJAMENTO (Markdown, lido pelo app de agenda)

1. Cabeçalho (frontmatter) entre linhas `---`, no topo:
   - projeto: nome do projeto (obrigatório)
   - area: Estudo, Trabalho, Pessoal ou Lazer (obrigatório, a não ser que use `dentro`)
   - dentro: caminho de um projeto que já existe, para criar como subprojeto (opcional;
     ex.: "Pós FIAP › Fase 3")
   - sequencial: true se as etapas devem liberar uma de cada vez, na ordem (opcional)
   - prioridade: baixa, media, alta ou critica (opcional; padrão: media)
   - obsidian: link "obsidian://open?vault=...&file=..." desta nota (opcional; no Obsidian:
     paleta de comandos > "Copy Obsidian URL")
2. `## Nome` cria uma etapa (subprojeto) do projeto; `### Nome` cria uma etapa dentro da
   última `##`; `####` desce mais um nível.
3. Cada tarefa é uma linha `- [ ] Título`, com campos opcionais separados por ` | `:
   - duração: `1h`, `1h30`, `45min`
   - links: `[rótulo](https://...)` (pode haver vários)
   - quantidade: `3 de 5 vídeos` (vira progresso "3/5 vídeos" com botão +1)
   - prioridade: `!baixa`, `!alta` ou `!critica`
   Exemplo: `- [ ] Escala de Dó | 45min | [vídeo](https://...) | 0 de 3 repetições`
4. `- [x]` = tarefa já concluída.
5. Texto comum (parágrafos e listas sem caixinha) vira as notas do projeto ou da etapa em que
   está. Linhas indentadas logo abaixo de uma tarefa viram as notas da tarefa.
6. `%% comentário %%` e títulos `#` (um só #) são ignorados.
7. Reimportar a mesma nota atualiza pelo nome (não duplica) e mantém o que já foi
   marcado/progredido no app.
"""

MODELO = """\
---
agenda: plano
projeto: Nome do objetivo
area: Estudo
sequencial: true
prioridade: media
obsidian:
---
%% Formato lido pelo app (resumo):
   ## = etapa · ### = etapa dentro da anterior · - [ ] = tarefa · - [x] = feita
   Campos da tarefa, separados por " | ": duração (1h, 45min) · [rótulo](url) · "3 de 5 aulas" · !alta
   Texto comum vira nota do projeto/etapa. Este bloco %% %% é ignorado. %%

# Objetivo
Onde quero chegar e em quanto tempo. Quanto tempo por semana tenho disponível.

## Semana 1
Meta da semana: …
- [ ] Primeiro tópico | 1h | [fonte](https://...)
- [ ] Segundo tópico | 45min
- [ ] Exercício prático | 30min | 0 de 3 repetições

## Semana 2
Meta da semana: …
- [ ] Tópico | 1h
"""

_PROMPT_REGRAS = """\
Responda SOMENTE com o Markdown do planejamento, começando pela linha `---` do cabeçalho,
sem comentários antes ou depois e sem bloco de código.

{formato}
Exemplo de saída válida:

{modelo}"""

PROMPT_CRIAR = """\
Você é especialista em montar planos de estudo e de prática eficazes. Monte um planejamento
para o objetivo abaixo, no formato exato descrito no final.

OBJETIVO: [o que quero aprender ou conseguir fazer]
NÍVEL ATUAL: [do zero / já sei o básico de …]
TEMPO DISPONÍVEL: [ex.: 3 h por semana, em 3 dias]
PRAZO: [ex.: 10 semanas]
PREFERÊNCIAS: [ex.: vídeos em português, materiais gratuitos, foco prático]
ÁREA NO APP: [Estudo / Trabalho / Pessoal / Lazer]

Como montar:
- Divida em etapas (`##`), normalmente uma por semana, em ordem de dificuldade, e use
  `sequencial: true`.
- Comece cada etapa com uma linha "Meta da semana: …" (o que a pessoa saberá fazer ao final).
- Respeite o tempo disponível: a soma das durações de cada etapa não deve passar dele.
- Cada tarefa deve ser concreta e verificável, com duração. Alterne teoria e prática e
  inclua revisões periódicas e um pequeno marco/projeto a cada poucas etapas.
- Indique 1 ou 2 fontes de qualidade por tarefa quando fizer sentido. Só coloque link se
  tiver certeza de que ele existe; se não tiver, escreva o nome da fonte sem link.
- Repetições ("faça 3 vezes") viram quantidade: `0 de 3 repetições`.

""" + _PROMPT_REGRAS

PROMPT_CONVERTER = """\
Reescreva o planejamento abaixo no formato exato descrito no final, sem perder conteúdo:
mantenha as etapas, tarefas, links e observações (observações viram texto comum da etapa ou
linhas indentadas abaixo da tarefa). Complete durações só quando estiverem claras no texto.
Mantenha `- [x]` nas tarefas que já estão concluídas.

PLANEJAMENTO ATUAL:
[cole aqui o seu planejamento]

""" + _PROMPT_REGRAS


def prompt(modo: str) -> str:
	base = PROMPT_CONVERTER if modo == "converter" else PROMPT_CRIAR
	return base.format(formato=FORMATO, modelo=MODELO)


# ---------------------------------------------------------------------------
# Leitura do Markdown
# ---------------------------------------------------------------------------
@dataclass
class TarefaPlano:
	titulo: str
	feito: bool = False
	duracao_min: int | None = None
	links: list[tuple[str, str]] = field(default_factory=list)
	qtd_atual: float | None = None
	qtd_total: float | None = None
	qtd_unidade: str | None = None
	prioridade: str | None = None
	notas: list[str] = field(default_factory=list)


@dataclass
class EtapaPlano:
	nome: str
	nivel: int  # 1 = o projeto; 2 = ##; 3 = ###…
	notas: list[str] = field(default_factory=list)
	tarefas: list[TarefaPlano] = field(default_factory=list)
	etapas: list["EtapaPlano"] = field(default_factory=list)


@dataclass
class Plano:
	raiz: EtapaPlano
	area: str | None = None
	dentro: str | None = None
	sequencial: bool = False
	prioridade: str | None = None
	obsidian: str | None = None
	avisos: list[str] = field(default_factory=list)


class ErroPlano(ValueError):
	pass


_RE_LINK = re.compile(r"\[([^\]]*)\]\((\S+?)\)")
_RE_URL = re.compile(r"^(https?|obsidian)://\S+$")
_RE_QTD = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:de|/)\s*(\d+(?:[.,]\d+)?)\s*(.*)$", re.I)
_RE_TAREFA = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)$")
_RE_TITULO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_PRIORIDADES = {"baixa": "baixa", "media": "media", "média": "media", "alta": "alta", "critica": "critica", "crítica": "critica"}


def _num(txt: str) -> float:
	return float(txt.replace(",", "."))


def _frontmatter(linhas: list[str]) -> tuple[dict, list[str]]:
	if not linhas or linhas[0].strip() != "---":
		return {}, linhas
	for fim in range(1, len(linhas)):
		if linhas[fim].strip() == "---":
			meta = {}
			for l in linhas[1:fim]:
				if ":" in l and not l.lstrip().startswith("#"):
					k, v = l.split(":", 1)
					meta[k.strip().lower()] = v.strip().strip("\"'")
			return meta, linhas[fim + 1 :]
	raise ErroPlano("o cabeçalho (frontmatter) abre com --- mas não fecha")


def _tarefa(texto: str, feito: bool, avisos: list[str], nlinha: int) -> TarefaPlano:
	texto = texto.strip()
	if texto.startswith("|"):  # "- [ ] | 1h": sem título
		texto = " " + texto
	partes = [p.strip() for p in texto.split(" | ")]
	titulo_bruto, campos = partes[0], partes[1:]
	t = TarefaPlano(titulo="", feito=feito)
	# links no título: ficam só como texto no título e entram na lista de links
	for rot, url in _RE_LINK.findall(titulo_bruto):
		t.links.append((rot or url, url))
	t.titulo = _RE_LINK.sub(lambda m: m.group(1), titulo_bruto).strip()
	for c in campos:
		if not c:
			continue
		achados = _RE_LINK.findall(c)
		if achados:
			t.links += [(rot or url, url) for rot, url in achados]
			if _RE_LINK.sub("", c).strip(" ,;"):
				t.notas.append(c)
			continue
		if _RE_URL.match(c):
			t.links.append((c.split("//", 1)[1].split("/", 1)[0], c))
			continue
		if c.startswith("!") and c[1:].lower() in _PRIORIDADES:
			t.prioridade = _PRIORIDADES[c[1:].lower()]
			continue
		if m := _RE_QTD.match(c):
			t.qtd_atual, t.qtd_total = _num(m.group(1)), _num(m.group(2))
			t.qtd_unidade = m.group(3).strip()[:20] or None
			if not t.qtd_total:
				avisos.append(f"linha {nlinha}: quantidade com total 0 ignorada")
				t.qtd_atual = t.qtd_total = None
			continue
		try:
			d = duracao.ler(c)
		except ValueError:
			d = None
		if d:
			t.duracao_min = d
			continue
		t.notas.append(c)  # campo desconhecido: não se perde, vira nota
	if not t.titulo:
		raise ErroPlano(f"linha {nlinha}: tarefa sem título")
	t.titulo = t.titulo[:200]
	return t


def ler(texto: str) -> Plano:
	"""Converte o Markdown num Plano (sem tocar no banco). Levanta ErroPlano se inválido."""
	texto = texto.replace("\r\n", "\n").lstrip("﻿")
	# comentários do Obsidian (mantém as quebras de linha para os avisos citarem a linha certa)
	texto = re.sub(r"%%.*?%%", lambda m: "\n" * m.group(0).count("\n"), texto, flags=re.S)
	meta, linhas = _frontmatter(texto.split("\n"))
	nome = (meta.get("projeto") or "").strip()
	if not nome:
		raise ErroPlano("falta `projeto:` no cabeçalho (frontmatter)")
	plano = Plano(
		raiz=EtapaPlano(nome=nome[:120], nivel=1),
		area=meta.get("area") or meta.get("área") or None,
		dentro=meta.get("dentro") or None,
		sequencial=meta.get("sequencial", "").lower() in ("true", "sim", "yes", "1"),
		prioridade=_PRIORIDADES.get((meta.get("prioridade") or "").lower()),
		obsidian=meta.get("obsidian") or None,
	)
	if meta.get("prioridade") and not plano.prioridade:
		plano.avisos.append(f"prioridade {meta['prioridade']!r} desconhecida; usando a padrão")
	pilha = [plano.raiz]  # etapa atual em cada nível
	ultima: TarefaPlano | None = None
	ind_ultima = 0
	desloc = len(texto.split("\n")) - len(linhas)  # nº da linha real (após o frontmatter)
	for n, linha in enumerate(linhas, start=desloc + 1):
		if not linha.strip():
			continue
		if m := _RE_TITULO.match(linha):
			nivel = len(m.group(1))
			ultima = None
			if nivel == 1:  # "# Objetivo": o texto abaixo vai para as notas do projeto
				del pilha[1:]
				continue
			while len(pilha) > 1 and pilha[-1].nivel >= nivel:
				pilha.pop()
			if pilha[-1].nivel < nivel - 1:
				plano.avisos.append(f"linha {n}: '{m.group(2)}' pulou um nível; ficou dentro de '{pilha[-1].nome}'")
			etapa = EtapaPlano(nome=m.group(2).strip()[:120], nivel=pilha[-1].nivel + 1)
			pilha[-1].etapas.append(etapa)
			pilha.append(etapa)
			continue
		if m := _RE_TAREFA.match(linha):
			ind = len(m.group(1).expandtabs(4))
			ultima = _tarefa(m.group(3), m.group(2).lower() == "x", plano.avisos, n)
			ind_ultima = ind
			pilha[-1].tarefas.append(ultima)
			continue
		ind = len(linha) - len(linha.lstrip())
		if ultima is not None and ind > ind_ultima:
			ultima.notas.append(linha.strip())
		else:
			ultima = None
			pilha[-1].notas.append(linha.rstrip())
	return plano


# ---------------------------------------------------------------------------
# Aplicação no banco (ou simulação, para a prévia)
# ---------------------------------------------------------------------------
@dataclass
class Relatorio:
	projeto_id: int | None = None
	# (nível, tipo, nome, ação, concluída, minutos): minutos = duração da tarefa ou total da etapa
	linhas: list[tuple[int, str, str, str, bool, int]] = field(default_factory=list)
	contagem: dict[str, int] = field(default_factory=dict)
	mantidos: list[str] = field(default_factory=list)  # existem no app, não estão no plano
	avisos: list[str] = field(default_factory=list)

	def marcar(self, nivel: int, tipo: str, nome: str, acao: str, feito: bool = False, minutos: int = 0) -> None:
		self.linhas.append((nivel, tipo, nome, acao, feito, minutos))
		chave = f"{tipo}_{acao}"
		self.contagem[chave] = self.contagem.get(chave, 0) + 1


def _chave(nome: str) -> str:
	"""Comparação tolerante: sem acento, sem caixa e espaços normalizados."""
	sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
	return " ".join(sem_acento.casefold().split())


def _notas(linhas: list[str]) -> str | None:
	texto = "\n".join(linhas).strip()
	return texto or None


def _achar_area(session: Session, nome: str | None) -> Area | None:
	if not nome:
		return None
	for a in session.exec(select(Area)).all():
		if _chave(a.nome) == _chave(nome):
			return a
	return None


def _achar_projeto(session: Session, pai_id: int | None, nome: str) -> Projeto | None:
	cond = Projeto.pai_id == pai_id if pai_id is not None else Projeto.pai_id.is_(None)
	for p in session.exec(select(Projeto).where(cond)).all():
		if _chave(p.nome) == _chave(nome):
			return p
	return None


def _resolver_dentro(session: Session, caminho: str) -> Projeto:
	pai = None
	for parte in [p.strip() for p in re.split(r"›|>|/", caminho) if p.strip()]:
		achado = _achar_projeto(session, pai.id if pai else None, parte)
		if achado is None:
			raise ErroPlano(f"dentro: não encontrei o projeto '{parte}' em '{caminho}'")
		pai = achado
	if pai is None:
		raise ErroPlano("dentro: caminho vazio")
	return pai


def _mudou(obj, campos: dict) -> bool:
	alterou = False
	for k, v in campos.items():
		if getattr(obj, k) != v:
			setattr(obj, k, v)
			alterou = True
	if alterou and hasattr(obj, "atualizado_em"):
		obj.atualizado_em = datetime.now()
	return alterou


def _sincronizar_links(session: Session, links: list[tuple[str, str]], *, item_id=None, projeto_id=None) -> bool:
	"""Garante os links do plano; mantém links extras criados no app."""
	cond = Link.item_id == item_id if item_id is not None else Link.projeto_id == projeto_id
	existentes = {l.url: l for l in session.exec(select(Link).where(cond)).all()}
	alterou = False
	for rotulo, url in links:
		rotulo = rotulo[:80]
		if url in existentes:
			if existentes[url].rotulo != rotulo:
				existentes[url].rotulo = rotulo
				alterou = True
		else:
			session.add(Link(item_id=item_id, projeto_id=projeto_id, rotulo=rotulo, url=url))
			alterou = True
	return alterou


def _minutos(etapa: EtapaPlano) -> int:
	"""Soma das durações informadas na etapa (com subetapas)."""
	return sum(t.duracao_min or 0 for t in etapa.tarefas) + sum(_minutos(e) for e in etapa.etapas)


def _aplicar_tarefa(session: Session, t: TarefaPlano, projeto: Projeto, ordem: int, nivel: int, rel: Relatorio) -> None:
	existente = None
	for it in session.exec(select(Item).where(Item.projeto_id == projeto.id)).all():
		if _chave(it.titulo) == _chave(t.titulo):
			existente = it
			break
	campos: dict = {} if projeto.ordem_manual else {"ordem": ordem}  # ordem arrumada no app prevalece
	if existente is None and projeto.ordem_manual:  # novo num projeto com ordem manual: vai para o fim
		campos["ordem"] = max((i.ordem for i in session.exec(select(Item).where(Item.projeto_id == projeto.id))), default=0) + 1
	# Só sobrescreve o que o plano informa (notas/duração colocadas no app ficam)
	if t.duracao_min:
		campos["duracao_min"] = t.duracao_min
	if t.notas:
		campos["notas"] = _notas(t.notas)
	if t.prioridade:
		campos["prioridade"] = Prioridade(t.prioridade)
	if t.qtd_total:
		campos.update(progresso_modo=ProgressoModo.quantidade, progresso_total=t.qtd_total, progresso_unidade=t.qtd_unidade)
	if existente is None:
		item = Item(
			titulo=t.titulo,
			tipo=TipoItem.tarefa,
			projeto_id=projeto.id,
			area_id=projeto.area_id,
			prioridade=campos.pop("prioridade", projeto.prioridade),
			status=StatusItem.concluido if t.feito else StatusItem.a_fazer,
			progresso_atual=t.qtd_atual if t.qtd_total else None,
			**campos,
		)
		session.add(item)
		session.flush()
		_sincronizar_links(session, t.links, item_id=item.id)
		rel.marcar(nivel, "item", t.titulo, "novo", t.feito, t.duracao_min or 0)
		return
	# Atualização: não desfaz o que foi feito no app
	if t.feito and existente.status != StatusItem.concluido:
		campos["status"] = StatusItem.concluido
	if t.qtd_total:
		campos["progresso_atual"] = max(existente.progresso_atual or 0, t.qtd_atual or 0)
	alterou = _mudou(existente, campos)
	alterou = _sincronizar_links(session, t.links, item_id=existente.id) or alterou
	rel.marcar(nivel, "item", t.titulo, "atualizado" if alterou else "igual", existente.status == StatusItem.concluido, t.duracao_min or 0)


def _aplicar_etapa(session: Session, etapa: EtapaPlano, pai: Projeto, ordem: int, rel: Relatorio) -> Projeto:
	proj = _achar_projeto(session, pai.id, etapa.nome)
	campos = {} if pai.ordem_manual else {"ordem": ordem}  # ordem arrumada no app prevalece
	if proj is None and pai.ordem_manual:
		campos["ordem"] = max((p.ordem for p in session.exec(select(Projeto).where(Projeto.pai_id == pai.id))), default=0) + 1
	if etapa.notas:
		campos["notas"] = _notas(etapa.notas)
	if proj is None:
		proj = Projeto(nome=etapa.nome, pai_id=pai.id, area_id=pai.area_id, prioridade=pai.prioridade, **campos)
		session.add(proj)
		session.flush()
		rel.marcar(etapa.nivel, "etapa", etapa.nome, "novo", minutos=_minutos(etapa))
	else:
		rel.marcar(etapa.nivel, "etapa", etapa.nome, "atualizado" if _mudou(proj, campos) else "igual", minutos=_minutos(etapa))
	_aplicar_conteudo(session, etapa, proj, rel)
	return proj


def _aplicar_conteudo(session: Session, etapa: EtapaPlano, proj: Projeto, rel: Relatorio) -> None:
	nomes_tarefas = {_chave(t.titulo) for t in etapa.tarefas}
	nomes_etapas = {_chave(e.nome) for e in etapa.etapas}
	for n, t in enumerate(etapa.tarefas, start=1):
		_aplicar_tarefa(session, t, proj, n, etapa.nivel + 1, rel)
	for n, sub in enumerate(etapa.etapas, start=1):
		_aplicar_etapa(session, sub, proj, n, rel)
	# O que existe no app e não está no plano fica como está (nunca apaga)
	for it in session.exec(select(Item).where(Item.projeto_id == proj.id)).all():
		if _chave(it.titulo) not in nomes_tarefas:
			rel.mantidos.append(f"{proj.nome} › {it.titulo}")
	for p in session.exec(select(Projeto).where(Projeto.pai_id == proj.id)).all():
		if _chave(p.nome) not in nomes_etapas:
			rel.mantidos.append(f"{proj.nome} › {p.nome}")


def aplicar(session: Session, plano: Plano, simular: bool = False) -> Relatorio:
	"""Cria/atualiza o projeto do plano. Com `simular=True`, desfaz tudo no fim (prévia)."""
	rel = Relatorio(avisos=list(plano.avisos))
	try:
		pai = _resolver_dentro(session, plano.dentro) if plano.dentro else None
		area = _achar_area(session, plano.area)
		if plano.area and area is None:
			nomes = ", ".join(a.nome for a in session.exec(select(Area)).all())
			raise ErroPlano(f"área '{plano.area}' não existe (áreas: {nomes})")
		if area is None and pai is None:
			raise ErroPlano("informe `area:` no cabeçalho (ou `dentro:` com um projeto existente)")
		area_id = area.id if area else pai.area_id
		raiz = plano.raiz
		proj = _achar_projeto(session, pai.id if pai else None, raiz.nome)
		campos = {"area_id": area_id, "sequencial": plano.sequencial}
		if raiz.notas:
			campos["notas"] = _notas(raiz.notas)
		if plano.prioridade:
			campos["prioridade"] = Prioridade(plano.prioridade)
		if proj is None:
			prioridade = campos.pop("prioridade", pai.prioridade if pai else Prioridade.media)
			proj = Projeto(nome=raiz.nome, pai_id=pai.id if pai else None, prioridade=prioridade, **campos)
			session.add(proj)
			session.flush()
			rel.marcar(1, "projeto", raiz.nome, "novo", minutos=_minutos(raiz))
		else:
			rel.marcar(1, "projeto", raiz.nome, "atualizado" if _mudou(proj, campos) else "igual", minutos=_minutos(raiz))
		if plano.obsidian:
			_sincronizar_links(session, [("Planejamento (Obsidian)", plano.obsidian)], projeto_id=proj.id)
		_aplicar_conteudo(session, raiz, proj, rel)
		rel.projeto_id = proj.id
		if not raiz.tarefas and not raiz.etapas:
			rel.avisos.append("o plano não tem etapas (##) nem tarefas (- [ ])")
	except Exception:
		session.rollback()
		raise
	if simular:
		session.rollback()
	else:
		session.commit()
	return rel
