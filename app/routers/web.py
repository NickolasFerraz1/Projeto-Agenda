"""Interface web (PWA): páginas HTML renderizadas no servidor, com HTMX e Alpine.js.

As rotas daqui reaproveitam as funções da API (mesmas validações e regras); só cuidam
de converter formulário <-> modelos e de escolher o template.
"""
import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import ValidationError
from sqlmodel import Session, func, select

from app import config
from app.db import get_session
from app.models import (
	Area,
	Item,
	Ocorrencia,
	Prioridade,
	ProgressoModo,
	Projeto,
	StatusItem,
	StatusOcorrencia,
	StatusProjeto,
	TipoItem,
)
from app.routers import agenda as api_agenda
from app.routers import areas as api_areas
from app.routers import itens as api_itens
from app.routers import projetos as api_projetos
from app.routers.common import get_or_404, item_out
from app.schemas import AreaIn, AreaUpdate, ItemIn, ItemUpdate, ProjetoIn, ProjetoUpdate
from app.services import agendar, duracao, gcal, markdown, plano, recorrencia
from app.services.progresso import Arvore, ordem_natural

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=config.ROOT / "app" / "templates")
STATIC = config.ROOT / "app" / "static"

# ---------- Rótulos e filtros dos templates ----------
ROTULOS = {
	"prioridade": {"baixa": "Baixa", "media": "Média", "alta": "Alta", "critica": "Crítica"},
	"tipo": {"aula": "Aula", "atividade": "Atividade", "tarefa": "Tarefa", "compromisso": "Compromisso", "habito": "Hábito"},
	"status": {"a_fazer": "A fazer", "em_andamento": "Em andamento", "concluido": "Concluído", "cancelado": "Cancelado", "pulado": "Pulado"},
	"status_projeto": {"ativo": "Ativo", "pausado": "Pausado", "concluido": "Concluído", "arquivado": "Arquivado"},
	"progresso": {"nenhum": "Sem progresso", "manual": "Manual (%)", "quantidade": "Quantidade (ex.: 4 de 8 h)", "itens": "Automático (itens e subprojetos)"},
}
SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
SEMANA_LONGA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
ABERTOS = [StatusItem.a_fazer, StatusItem.em_andamento]


def _v(x):
	return x.value if hasattr(x, "value") else x


def _rotulo(valor, grupo):
	return ROTULOS[grupo].get(_v(valor), _v(valor))


def _hora(dt):
	return dt.strftime("%H:%M") if dt else ""


def _dia(d, longo=False):
	"""qui, 15 out   |   quinta, 15 de out"""
	if isinstance(d, datetime):
		d = d.date()
	if longo:
		return f"{SEMANA_LONGA[d.weekday()]}, {d.day} de {MESES[d.month - 1]}"
	return f"{SEMANA[d.weekday()]}, {d.day} {MESES[d.month - 1]}"


def _dia_curto(d):
	"""16 out"""
	return f"{d.day} {MESES[d.month - 1]}" if d else ""


def _num(x):
	"""4.0 -> 4 ; 4.5 -> 4,5"""
	if not isinstance(x, (int, float)):  # None ou campo ausente
		return ""
	return f"{x:g}".replace(".", ",")


ler_duracao = duracao.ler  # usado também pelos testes
_duracao_txt = duracao.texto


templates.env.filters.update(
	rotulo=_rotulo,
	hora=_hora,
	dia=_dia,
	dia_curto=_dia_curto,
	num=_num,
	duracao=_duracao_txt,
	markdown=lambda t: Markup(markdown.render(t)),
	v=_v,
	recorrencia=recorrencia.descrever,
)
templates.env.globals.update(
	ROTULOS=ROTULOS,
	PRIORIDADES=[p.value for p in Prioridade],
	TIPOS=[t.value for t in TipoItem],
	STATUS_ITEM=[s.value for s in StatusItem],
	STATUS_PROJETO=[s.value for s in StatusProjeto],
	MODOS=[m.value for m in ProgressoModo],
	DIAS=recorrencia.DIAS,
	DIAS_NOME=recorrencia.DIAS_NOME,
	VERSAO=config.ASSET_VERSION,
)


def render(request: Request, nome: str, session: Session | None = None, **ctx) -> HTMLResponse:
	if session is not None:
		ctx.setdefault("areas", session.exec(select(Area).order_by(Area.nome)).all())
	ctx.setdefault("hoje", date.today())
	ctx.setdefault("google", gcal.ESTADO)
	ctx.setdefault("gcal_id", config.GCAL_ID)
	if not nome.startswith("partials/"):
		ctx.setdefault("avisos_globais", agendar.consumir_avisos())
	return templates.TemplateResponse(request, nome, ctx)


def _com_avisos(resp: HTMLResponse) -> HTMLResponse:
	"""Respostas parciais (HTMX): avisos vão no cabeçalho HX-Trigger e viram um toast."""
	avisos = agendar.consumir_avisos()
	if avisos:
		import json

		resp.headers["HX-Trigger"] = json.dumps({"aviso": avisos}, ensure_ascii=True)
	return resp


def _voltar(destino: str | None, padrao: str = "/") -> str:
	"""Só aceita caminhos locais (evita redirecionar para fora)."""
	if destino and destino.startswith("/") and not destino.startswith("//"):
		return destino
	return padrao


def _redirect(url: str) -> RedirectResponse:
	return RedirectResponse(url, status_code=303)


def _erros(exc: Exception) -> list[str]:
	if isinstance(exc, HTTPException):
		return [str(exc.detail)]
	if isinstance(exc, ValidationError):
		msgs = []
		for e in exc.errors():
			campo = ".".join(str(p) for p in e["loc"] if p != "body")
			msg = e["msg"].removeprefix("Value error, ")
			msgs.append(f"{campo}: {msg}" if campo else msg)
		return msgs
	return [str(exc)]


def _texto(form, chave) -> str | None:
	v = (form.get(chave) or "").strip()
	return v or None


def _int(form, chave) -> int | None:
	v = _texto(form, chave)
	return int(v) if v else None


def _float(form, chave) -> float | None:
	v = _texto(form, chave)
	return float(v.replace(",", ".")) if v else None


def _data(form, chave) -> date | None:
	v = _texto(form, chave)
	return date.fromisoformat(v) if v else None


def _hora_form(form, chave) -> time | None:
	v = _texto(form, chave)
	return time.fromisoformat(v) if v else None


def _links_form(form) -> list[dict]:
	rotulos, urls = form.getlist("link_rotulo"), form.getlist("link_url")
	links = []
	for rotulo, url in zip(rotulos, urls):
		rotulo, url = rotulo.strip(), url.strip()
		if url:
			links.append({"rotulo": rotulo or url[:80], "url": url})
	return links


def _progresso_form(form) -> dict:
	return {
		"progresso_modo": form.get("progresso_modo") or "nenhum",
		"progresso_manual": _float(form, "progresso_manual"),
		"progresso_atual": _float(form, "progresso_atual"),
		"progresso_total": _float(form, "progresso_total"),
		"progresso_unidade": _texto(form, "progresso_unidade"),
	}


# ---------- PWA ----------
@router.get("/manifest.webmanifest")
def manifest():
	return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker(request: Request):
	# Servido na raiz para controlar o app inteiro; gerado pelo template para versionar o cache.
	resp = templates.TemplateResponse(request, "sw.js", {}, media_type="application/javascript")
	resp.headers["Cache-Control"] = "no-cache"
	resp.headers["Service-Worker-Allowed"] = "/"
	return resp


@router.get("/offline", response_class=HTMLResponse)
def offline(request: Request):
	return render(request, "offline.html")


# ---------- Hoje ----------
def _ctx_hoje(session: Session, dia: date) -> dict:
	return {"resumo": api_agenda.hoje(dia, session), "dia": dia, "caminhos": _caminhos(session), "sugestoes": _sugestoes_agendar(session)}


@router.get("/", response_class=HTMLResponse)
def pagina_hoje(request: Request, session: Session = Depends(get_session)):
	return render(request, "hoje.html", session, **_ctx_hoje(session, date.today()))


@router.post("/captura", response_class=HTMLResponse)
async def captura(request: Request, session: Session = Depends(get_session)):
	"""Captura rápida: título + (opcional) quando, área e prioridade."""
	form = await request.form()
	quando, hora = form.get("quando") or "", _hora_form(form, "hora")
	dados = {
		"titulo": _texto(form, "titulo"),
		"area_id": _int(form, "area_id"),
		"prioridade": form.get("prioridade") or "media",
	}
	dia = {"hoje": date.today(), "amanha": date.today() + timedelta(days=1)}.get(quando)
	if dia:
		dados["inicio"] = datetime.combine(dia, hora or time.min)
		dados["dia_inteiro"] = hora is None
	erros = []
	try:
		api_itens.criar(ItemIn.model_validate(dados), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		erros = _erros(exc)
	ctx = _ctx_hoje(session, date.today())
	if request.headers.get("HX-Request"):
		return render(request, "partials/hoje_listas.html", session, erros_captura=erros, **ctx)
	return render(request, "hoje.html", session, erros_captura=erros, **ctx)


# ---------- Marcar como feito ----------
def _linha_entrada(session: Session, item: Item, tipo: str, dia: date):
	areas = {a.id: a for a in session.exec(select(Area)).all()}
	projetos = {p.id: p for p in session.exec(select(Projeto)).all()}
	if item.recorrencia:
		oc = session.exec(select(Ocorrencia).where(Ocorrencia.item_id == item.id, Ocorrencia.data == dia)).first()
		inicio = datetime.combine(dia, item.inicio.time())
		dur = recorrencia.duracao(item.inicio, item.fim)
		status = oc.status.value if oc else "a_fazer"
		return api_agenda._entrada(item, "agendado", dia, inicio, inicio + dur if dur else None, status, areas, projetos, session)
	inicio = item.prazo if tipo == "prazo" else item.inicio
	fim = None if tipo == "prazo" else item.fim
	return api_agenda._entrada(item, tipo, dia, inicio, fim, item.status.value, areas, projetos, session)


@router.post("/alternar/{item_id}", response_class=HTMLResponse)
def alternar(
	request: Request,
	item_id: int,
	tipo: str = "item",  # "agendado" | "prazo" (linha da agenda) | "item" (linha de lista)
	dia: date | None = None,
	rel: int | None = None,  # página do projeto: caminhos relativos a ele
	session: Session = Depends(get_session),
):
	"""Marca/desmarca como feito. Recorrente: só o dia. Os demais: o item inteiro."""
	item = get_or_404(session, Item, item_id)
	if item.recorrencia and dia:
		oc = session.exec(select(Ocorrencia).where(Ocorrencia.item_id == item_id, Ocorrencia.data == dia)).first()
		if oc and oc.status == StatusOcorrencia.concluido:
			session.delete(oc)  # desmarca
		elif oc:
			oc.status = StatusOcorrencia.concluido  # estava pulado: passa a feito
		else:
			session.add(Ocorrencia(item_id=item_id, data=dia, status=StatusOcorrencia.concluido))
	else:
		item.status = StatusItem.a_fazer if item.status == StatusItem.concluido else StatusItem.concluido
		item.atualizado_em = datetime.now()
	session.commit()
	session.refresh(item)
	if not item.recorrencia and item.status == StatusItem.concluido:
		agendar.ao_concluir(session, item)
		session.refresh(item)
	if tipo in ("agendado", "prazo") and dia:
		return _com_avisos(render(request, "partials/linha_entrada.html", e=_linha_entrada(session, item, tipo, dia)))
	return _com_avisos(
		render(request, "partials/linha_item.html", session, i=item_out(session, item), caminhos=_caminhos(session, rel), rel=rel)
	)


@router.post("/pular/{item_id}", response_class=HTMLResponse)
def pular(request: Request, item_id: int, dia: date, session: Session = Depends(get_session)):
	"""Recorrente: marca o dia como pulado (não fez e não vai fazer). De novo no mesmo dia: desfaz."""
	item = get_or_404(session, Item, item_id)
	if not item.recorrencia:
		raise HTTPException(422, "só itens recorrentes podem pular um dia")
	if not recorrencia.ocorrencias(item.recorrencia, item.inicio, dia, dia):
		raise HTTPException(422, "este item não acontece nesse dia")
	oc = session.exec(select(Ocorrencia).where(Ocorrencia.item_id == item_id, Ocorrencia.data == dia)).first()
	if oc and oc.status == StatusOcorrencia.pulado:
		session.delete(oc)
	elif oc:
		oc.status = StatusOcorrencia.pulado
	else:
		session.add(Ocorrencia(item_id=item_id, data=dia, status=StatusOcorrencia.pulado))
	session.commit()
	return render(request, "partials/linha_entrada.html", e=_linha_entrada(session, item, "agendado", dia))


@router.post("/incrementar/{item_id}", response_class=HTMLResponse)
def incrementar(request: Request, item_id: int, rel: int | None = None, session: Session = Depends(get_session)):
	"""Botão +1 dos itens com progresso por quantidade ("assisti mais uma aula").
	Ao chegar no total, o item é concluído."""
	item = get_or_404(session, Item, item_id)
	if item.progresso_modo != ProgressoModo.quantidade:
		raise HTTPException(422, "só itens com progresso por quantidade")
	atual = (item.progresso_atual or 0) + 1
	if item.progresso_total:
		atual = min(atual, item.progresso_total)
		if atual >= item.progresso_total:
			item.status = StatusItem.concluido
	item.progresso_atual = atual
	item.atualizado_em = datetime.now()
	session.commit()
	session.refresh(item)
	if item.status == StatusItem.concluido:
		agendar.ao_concluir(session, item)
		session.refresh(item)
	return _com_avisos(
		render(request, "partials/linha_item.html", session, i=item_out(session, item), caminhos=_caminhos(session, rel), rel=rel)
	)


@router.post("/markdown", response_class=HTMLResponse)
async def previa_markdown(request: Request):
	"""Pré-visualização das notas (formulários)."""
	form = await request.form()
	html = markdown.render(form.get("notas") or "")
	return HTMLResponse(html or '<p class="vazio">Nada para mostrar.</p>')


def _caminhos(session: Session, ocultar: int | None = None) -> dict[int, str]:
	"""projeto_id -> "Pós FIAP › Fase 3 › CI/CD" (sem os níveis até `ocultar`, se informado)."""
	arv = Arvore.carregar(session)
	res = {}
	for pid in arv.projetos:
		cam = arv.caminho(pid)
		if ocultar is not None:
			ids = [p.id for p in cam]
			if ocultar in ids:
				cam = cam[ids.index(ocultar) + 1 :]
		res[pid] = " › ".join(p.nome for p in cam)
	return res


# ---------- Semana ----------
@router.get("/semana", response_class=HTMLResponse)
def pagina_semana(request: Request, inicio: date | None = None, session: Session = Depends(get_session)):
	base = inicio or date.today()
	seg = base - timedelta(days=base.weekday())
	dom = seg + timedelta(days=6)
	entradas = api_agenda.montar_agenda(session, seg, dom)
	dias = [(seg + timedelta(days=n), [e for e in entradas if e.data == seg + timedelta(days=n)]) for n in range(7)]
	return render(
		request,
		"semana.html",
		session,
		dias=dias,
		seg=seg,
		dom=dom,
		anterior=seg - timedelta(days=7),
		proxima=seg + timedelta(days=7),
	)


# ---------- Projetos ----------
def _abertos_na_subarvore(session: Session, arv: Arvore) -> dict[int, int]:
	"""Quantos itens em aberto cada projeto tem, contando os subprojetos."""
	diretos = dict(
		session.exec(
			select(Item.projeto_id, func.count()).where(Item.projeto_id.is_not(None), Item.status.in_(ABERTOS)).group_by(Item.projeto_id)
		).all()
	)
	return {pid: sum(diretos.get(x, 0) for x in {pid} | arv.descendentes(pid)) for pid in arv.projetos}


@router.get("/projetos", response_class=HTMLResponse)
def pagina_projetos(request: Request, status: str = "ativo", session: Session = Depends(get_session)):
	filtro = StatusProjeto(status) if status in ROTULOS["status_projeto"] else None
	projetos = api_projetos.listar(status=filtro, raiz=True, session=session)
	arv = Arvore.carregar(session)
	subs = {pid: len(arv.filhos.get(pid, [])) for pid in arv.projetos}
	return render(
		request, "projetos.html", session,
		projetos=projetos, abertos=_abertos_na_subarvore(session, arv), subs=subs, status=status if filtro else "todos",
	)


def _opcoes_pai(session: Session, excluir: int | None = None) -> list[tuple[int, str]]:
	"""(id, caminho) em ordem de árvore; exclui o próprio projeto e os descendentes dele."""
	arv = Arvore.carregar(session)
	proibidos = ({excluir} | arv.descendentes(excluir)) if excluir else set()
	opcoes: list[tuple[int, str]] = []

	def visitar(pai_id):
		raizes = arv.filhos.get(pai_id, [])
		if pai_id is None:
			raizes = sorted(raizes, key=lambda p: ordem_natural(p.nome))
		for p in raizes:
			if p.id in proibidos:
				continue
			opcoes.append((p.id, arv.caminho_texto(p.id)))
			visitar(p.id)

	visitar(None)
	return opcoes


@router.get("/projetos/novo", response_class=HTMLResponse)
def novo_projeto(request: Request, pai_id: int | None = None, session: Session = Depends(get_session)):
	f = {"prioridade": "", "status": "ativo", "progresso_modo": "itens", "links": [], "pai_id": pai_id, "area_id": None, "ordem": 0}
	return render(request, "projeto_form.html", session, f=f, projeto=None, opcoes_pai=_opcoes_pai(session))


def _projeto_payload(form) -> dict:
	return {
		"nome": _texto(form, "nome"),
		"pai_id": _int(form, "pai_id"),
		"area_id": _int(form, "area_id"),
		"prioridade": form.get("prioridade") or None,
		"status": form.get("status") or "ativo",
		"ordem": _int(form, "ordem") or 0,
		"sequencial": form.get("sequencial") == "on",
		"agenda_auto": form.get("agenda_auto") == "on",
		"link": _texto(form, "link"),
		"notas": _texto(form, "notas"),
		"links": _links_form(form),
		**_progresso_form(form),
	}


@router.post("/projetos/novo", response_class=HTMLResponse)
async def criar_projeto(request: Request, session: Session = Depends(get_session)):
	payload = _projeto_payload(await request.form())
	try:
		projeto = api_projetos.criar(ProjetoIn.model_validate(payload), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		return render(request, "projeto_form.html", session, f=payload, projeto=None, opcoes_pai=_opcoes_pai(session), erros=_erros(exc))
	return _redirect(f"/projetos/{projeto.id}")


@router.get("/projetos/{projeto_id}", response_class=HTMLResponse)
def pagina_projeto(request: Request, projeto_id: int, session: Session = Depends(get_session)):
	projeto = api_projetos.obter(projeto_id, session)
	arv = Arvore.carregar(session)
	subprojetos = api_projetos.listar(pai_id=projeto_id, session=session)
	itens = api_projetos.itens(projeto_id, session)
	ordem = lambda i: (i.ordem, -i.prioridade.peso, ordem_natural(i.titulo))  # noqa: E731
	abertos = sorted([i for i in itens if i.status in ABERTOS], key=ordem)
	fechados = sorted([i for i in itens if i.status not in ABERTOS], key=ordem)
	return render(
		request, "projeto.html", session,
		p=projeto,
		trilha=arv.caminho(projeto_id)[:-1],
		subprojetos=subprojetos,
		abertos_sub=_abertos_na_subarvore(session, arv),
		abertos=abertos,
		fechados=fechados,
		caminhos=_caminhos(session, ocultar=projeto_id),
		etapa_para_agendar=agendar.proxima_para_agendar(session, projeto_id),
		horarios=agendar.horarios_herdados(session, projeto_id)[0],
	)


@router.get("/projetos/{projeto_id}/editar", response_class=HTMLResponse)
def editar_projeto(request: Request, projeto_id: int, session: Session = Depends(get_session)):
	p = api_projetos.obter(projeto_id, session)
	f = p.model_dump(mode="json")
	return render(request, "projeto_form.html", session, f=f, projeto=p, opcoes_pai=_opcoes_pai(session, excluir=projeto_id))


@router.post("/projetos/{projeto_id}/editar", response_class=HTMLResponse)
async def salvar_projeto(request: Request, projeto_id: int, session: Session = Depends(get_session)):
	payload = _projeto_payload(await request.form())
	if payload["prioridade"] is None:
		payload.pop("prioridade")
	if payload["area_id"] is None:  # "do projeto-pai"
		pai = session.get(Projeto, payload["pai_id"]) if payload["pai_id"] else None
		if pai:
			payload["area_id"] = pai.area_id
		else:
			payload.pop("area_id")
	try:
		api_projetos.atualizar(projeto_id, ProjetoUpdate.model_validate(payload), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		p = api_projetos.obter(projeto_id, session)
		return render(
			request, "projeto_form.html", session, f=payload, projeto=p, opcoes_pai=_opcoes_pai(session, excluir=projeto_id), erros=_erros(exc)
		)
	return _redirect(f"/projetos/{projeto_id}")


@router.post("/projetos/{projeto_id}/excluir")
def excluir_projeto(projeto_id: int, session: Session = Depends(get_session)):
	pai_id = api_projetos.obter(projeto_id, session).pai_id
	api_projetos.excluir(projeto_id, session)
	return _redirect(f"/projetos/{pai_id}" if pai_id else "/projetos")


# ---------- Itens ----------
def _form_de_item(item) -> dict:
	"""ItemOut -> campos do formulário (data e hora separadas, recorrência em presets)."""
	d = item.model_dump(mode="json")
	ini, fim, prazo = item.inicio, item.fim, item.prazo
	rep = recorrencia.ler_regra(item.recorrencia)
	d.update(
		data=ini.date().isoformat() if ini else "",
		hora_inicio="" if (not ini or item.dia_inteiro) else _hora(ini),
		hora_fim="" if (not fim or item.dia_inteiro) else _hora(fim),
		prazo_data=prazo.date().isoformat() if prazo else "",
		prazo_hora=_hora(prazo) if prazo and prazo.time() != time(23, 59) else "",
		rep_freq=rep["freq"],
		rep_dias=rep["dias"],
		rep_ate=rep["ate"].isoformat() if rep["ate"] else "",
		rep_custom=rep["custom"],
		duracao=_duracao_txt(item.duracao_min),
	)
	return d


def _item_payload(form) -> dict:
	"""Campos do formulário -> dicionário no formato da API (ItemIn/ItemUpdate)."""
	dia, h_ini, h_fim = _data(form, "data"), _hora_form(form, "hora_inicio"), _hora_form(form, "hora_fim")
	prazo_dia, prazo_h = _data(form, "prazo_data"), _hora_form(form, "prazo_hora")
	dia_inteiro = bool(dia) and h_ini is None
	payload = {
		"titulo": _texto(form, "titulo"),
		"tipo": form.get("tipo") or "tarefa",
		"projeto_id": _int(form, "projeto_id"),
		"area_id": _int(form, "area_id"),
		"prioridade": form.get("prioridade") or None,
		"status": form.get("status") or "a_fazer",
		"inicio": datetime.combine(dia, h_ini or time.min) if dia else None,
		"fim": datetime.combine(dia, h_fim) if dia and h_fim and not dia_inteiro else None,
		"dia_inteiro": dia_inteiro,
		"prazo": datetime.combine(prazo_dia, prazo_h or time(23, 59)) if prazo_dia else None,
		"notas": _texto(form, "notas"),
		"_erros": [],
		"links": _links_form(form),
		**_progresso_form(form),
	}
	try:
		payload["duracao_min"] = ler_duracao(form.get("duracao"))
	except ValueError as exc:
		payload["duracao_min"] = None
		payload["_erros"].append(str(exc))
	freq = form.get("rep_freq") or ""
	if freq and not dia:
		payload["recorrencia"] = None
		payload["_erros"].append("para repetir, escolha o dia de início em \"Quando fazer\"")
		return payload
	try:
		payload["recorrencia"] = recorrencia.montar_regra(freq, form.getlist("rep_dias"), _data(form, "rep_ate"), form.get("rep_custom") or "")
	except (ValueError, TypeError) as exc:
		payload["recorrencia"] = None
		payload["_erros"].append(f"recorrência inválida: {exc}")
	return payload


def _form_de_payload(form, payload) -> dict:
	"""Para reexibir o formulário com o que o usuário digitou (após erro)."""
	f = {k: v for k, v in payload.items() if not k.startswith("_")}
	for chave in ("data", "hora_inicio", "hora_fim", "prazo_data", "prazo_hora", "rep_freq", "rep_ate", "rep_custom", "duracao"):
		f[chave] = form.get(chave) or ""
	f["rep_dias"] = form.getlist("rep_dias")
	f["prioridade"] = form.get("prioridade") or ""
	return f


def _ctx_item_form(session: Session) -> dict:
	"""Projetos ativos/pausados com o caminho completo ("Piano › Semana 2")."""
	arv = Arvore.carregar(session)
	ok = {StatusProjeto.ativo, StatusProjeto.pausado}
	opcoes = [(pid, txt) for pid, txt in _opcoes_pai(session) if arv.projetos[pid].status in ok]
	return {"projetos_lista": opcoes}


@router.get("/itens/novo", response_class=HTMLResponse)
def novo_item(
	request: Request,
	projeto_id: int | None = None,
	data: date | None = None,
	voltar: str | None = None,
	session: Session = Depends(get_session),
):
	f = {
		"tipo": "tarefa",
		"status": "a_fazer",
		"prioridade": "",
		"projeto_id": projeto_id,
		"area_id": None,
		"data": data.isoformat() if data else "",
		"progresso_modo": "nenhum",
		"rep_freq": "",
		"rep_dias": [],
		"links": [],
	}
	padrao = f"/projetos/{projeto_id}" if projeto_id else "/"
	return render(request, "item_form.html", session, f=f, item=None, voltar=_voltar(voltar, padrao), **_ctx_item_form(session))


@router.post("/itens/novo", response_class=HTMLResponse)
async def criar_item(request: Request, session: Session = Depends(get_session)):
	form = await request.form()
	payload = _item_payload(form)
	voltar = _voltar(form.get("voltar"))
	try:
		if payload["_erros"]:
			raise HTTPException(422, "; ".join(payload["_erros"]))
		api_itens.criar(ItemIn.model_validate(payload), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		return render(
			request, "item_form.html", session, f=_form_de_payload(form, payload), item=None, voltar=voltar, erros=_erros(exc), **_ctx_item_form(session)
		)
	return _redirect(voltar)


@router.get("/itens/{item_id}", response_class=HTMLResponse)
def editar_item(request: Request, item_id: int, voltar: str | None = None, session: Session = Depends(get_session)):
	item = api_itens.obter(item_id, session)
	padrao = f"/projetos/{item.projeto_id}" if item.projeto_id else "/"
	return render(
		request, "item_form.html", session, f=_form_de_item(item), item=item, voltar=_voltar(voltar, padrao), **_ctx_item_form(session)
	)


@router.post("/itens/{item_id}", response_class=HTMLResponse)
async def salvar_item(request: Request, item_id: int, session: Session = Depends(get_session)):
	form = await request.form()
	payload = _item_payload(form)
	voltar = _voltar(form.get("voltar"))
	if payload["prioridade"] is None:  # na edição a prioridade é sempre explícita
		payload.pop("prioridade")
	if payload["area_id"] is None:  # "(do projeto)": usa a área do projeto
		projeto = session.get(Projeto, payload["projeto_id"]) if payload["projeto_id"] else None
		if projeto:
			payload["area_id"] = projeto.area_id
		else:
			payload.pop("area_id")
	try:
		if payload["_erros"]:
			raise HTTPException(422, "; ".join(payload["_erros"]))
		if "area_id" not in payload:
			raise HTTPException(422, "escolha uma área (ou um projeto)")
		api_itens.atualizar(item_id, ItemUpdate.model_validate(payload), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		item = api_itens.obter(item_id, session)
		return render(
			request, "item_form.html", session, f=_form_de_payload(form, payload), item=item, voltar=voltar, erros=_erros(exc), **_ctx_item_form(session)
		)
	return _redirect(voltar)


@router.post("/itens/{item_id}/excluir")
async def excluir_item(request: Request, item_id: int, session: Session = Depends(get_session)):
	form = await request.form()
	api_itens.excluir(item_id, session)
	return _redirect(_voltar(form.get("voltar")))


# ---------- Áreas ----------
@router.get("/areas", response_class=HTMLResponse)
def pagina_areas(request: Request, session: Session = Depends(get_session)):
	return render(request, "areas.html", session, google=gcal.ESTADO, gcal_id=config.GCAL_ID)


@router.post("/google/sincronizar")
def google_sincronizar(request: Request):
	"""Botão "Sincronizar agora" (roda na hora, em vez de esperar a próxima rodada).
	Via HTMX devolve só o cartão atualizado + um toast com o resultado."""
	res = gcal.rodar_agora()
	if not request.headers.get("HX-Request"):
		return _redirect("/areas")
	if res is None:
		agendar.avisar(f"Falha ao sincronizar: {gcal.ESTADO.erro or 'Google indisponível'}")
	elif res.erros:
		agendar.avisar(f"Sincronizado com {len(res.erros)} erro(s): veja o cartão do Google.")
	elif res.criados or res.atualizados or res.apagados:
		agendar.avisar(f"Sincronizado: {res.criados} criados, {res.atualizados} atualizados, {res.apagados} apagados.")
	else:
		agendar.avisar("Sincronizado: a agenda já estava em dia.")
	return _com_avisos(render(request, "partials/google_cartao.html"))


@router.post("/areas", response_class=HTMLResponse)
async def criar_area(request: Request, session: Session = Depends(get_session)):
	form = await request.form()
	try:
		api_areas.criar(AreaIn(nome=_texto(form, "nome") or "", cor=form.get("cor") or "#999999"), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		return render(request, "areas.html", session, erros=_erros(exc))
	return _redirect("/areas")


@router.post("/areas/{area_id}", response_class=HTMLResponse)
async def salvar_area(request: Request, area_id: int, session: Session = Depends(get_session)):
	form = await request.form()
	try:
		api_areas.atualizar(area_id, AreaUpdate(nome=_texto(form, "nome"), cor=form.get("cor")), session)
	except (ValidationError, HTTPException) as exc:
		session.rollback()
		return render(request, "areas.html", session, erros=_erros(exc))
	return _redirect("/areas")


@router.post("/areas/{area_id}/excluir", response_class=HTMLResponse)
def excluir_area(request: Request, area_id: int, session: Session = Depends(get_session)):
	try:
		api_areas.excluir(area_id, session)
	except HTTPException as exc:
		return render(request, "areas.html", session, erros=_erros(exc))
	return _redirect("/areas")


# ---------- Importar planejamento ----------
@router.get("/importar", response_class=HTMLResponse)
def pagina_importar(request: Request, session: Session = Depends(get_session)):
	return render(
		request, "importar.html", session,
		aba="projetos", modelo=plano.MODELO, formato=plano.FORMATO,
		prompt_criar=plano.prompt("criar"), prompt_converter=plano.prompt("converter"),
	)


@router.get("/importar/modelo.md")
def baixar_modelo():
	return Response(
		plano.MODELO, media_type="text/markdown; charset=utf-8",
		headers={"Content-Disposition": 'attachment; filename="Planejamento.md"'},
	)


@router.post("/importar/previa", response_class=HTMLResponse)
async def previa_importacao(request: Request, session: Session = Depends(get_session)):
	texto = (await request.form()).get("texto") or ""
	try:
		rel = plano.aplicar(session, plano.ler(texto), simular=True)
	except plano.ErroPlano as exc:
		return render(request, "partials/importar_previa.html", erro=str(exc))
	return render(request, "partials/importar_previa.html", rel=rel)


@router.post("/importar/aplicar", response_class=HTMLResponse)
async def aplicar_importacao(request: Request, session: Session = Depends(get_session)):
	texto = (await request.form()).get("texto") or ""
	try:
		rel = plano.aplicar(session, plano.ler(texto), simular=False)
	except plano.ErroPlano as exc:
		return render(
			request, "importar.html", session,
			aba="projetos", modelo=plano.MODELO, formato=plano.FORMATO,
			prompt_criar=plano.prompt("criar"), prompt_converter=plano.prompt("converter"),
			texto=texto, erros=[str(exc)],
		)
	return _redirect(f"/projetos/{rel.projeto_id}")


# ---------- Agendar etapa ----------
def _form_agendar(form) -> tuple[agendar.Horarios | None, date | None, bool, bool, list[str]]:
	erros = []
	dias = [d for d in form.getlist("dias") if d in recorrencia.DIAS]
	hora = _hora_form(form, "hora")
	minutos = _int(form, "minutos")
	if not dias:
		erros.append("escolha pelo menos um dia da semana")
	if hora is None:
		erros.append("informe o horário de início")
	if not minutos or minutos < 10:
		erros.append("a sessão precisa ter pelo menos 10 minutos")
	h = agendar.Horarios(dias, hora, minutos) if not erros else None
	# atrasadas: "nao" | "livres" (encaixa nos espaços livres) | "empurrar" (mantém a ordem, empurra as seguintes)
	modo = form.get("atrasadas") or ("livres" if form.get("remarcar") == "on" else "nao")
	return h, _data(form, "a_partir"), modo in ("livres", "empurrar"), modo == "empurrar", erros


@router.get("/projetos/{projeto_id}/agendar", response_class=HTMLResponse)
def pagina_agendar(request: Request, projeto_id: int, session: Session = Depends(get_session)):
	p = api_projetos.obter(projeto_id, session)
	h, destino = agendar.horarios_herdados(session, projeto_id)
	plano_destino = session.get(Projeto, destino)
	f = {
		"dias": h.dias if h else [],
		"hora": h.hora.strftime("%H:%M") if h else "19:00",
		"minutos": h.minutos if h else 60,
		"a_partir": date.today().isoformat(),
		"atrasadas": "livres",
		"auto": plano_destino.agenda_auto,
	}
	return render(request, "agendar.html", session, aba="projetos", p=p, f=f, herdado=h, plano_destino=plano_destino)


@router.post("/projetos/{projeto_id}/agendar/previa", response_class=HTMLResponse)
async def previa_agendar(request: Request, projeto_id: int, session: Session = Depends(get_session)):
	h, a_partir, remarcar, empurrar, erros = _form_agendar(await request.form())
	if erros:
		return render(request, "partials/agendar_previa.html", erros=erros)
	ag = agendar.planejar(session, projeto_id, h, a_partir, remarcar, empurrar=empurrar)
	return render(request, "partials/agendar_previa.html", ag=ag)


@router.post("/projetos/{projeto_id}/agendar", response_class=HTMLResponse)
async def confirmar_agendar(request: Request, projeto_id: int, session: Session = Depends(get_session)):
	form = await request.form()
	h, a_partir, remarcar, empurrar, erros = _form_agendar(form)
	if erros:
		p = api_projetos.obter(projeto_id, session)
		f = {
			"dias": form.getlist("dias"), "hora": form.get("hora"), "minutos": form.get("minutos"),
			"a_partir": form.get("a_partir"), "atrasadas": form.get("atrasadas") or "livres",
		}
		plano_destino = session.get(Projeto, agendar.horarios_herdados(session, projeto_id)[1])
		return render(request, "agendar.html", session, aba="projetos", p=p, f=f, herdado=None, plano_destino=plano_destino, erros=erros)
	ag = agendar.planejar(session, projeto_id, h, a_partir, remarcar, empurrar=empurrar)
	_, destino = agendar.horarios_herdados(session, projeto_id)
	agendar.aplicar(session, projeto_id, ag, guardar_em=destino)
	plano_destino = session.get(Projeto, destino)
	if plano_destino.sequencial:
		plano_destino.agenda_auto = form.get("auto") == "on"
		session.commit()
	return _redirect(f"/projetos/{projeto_id}")


@router.post("/projetos/{projeto_id}/desagendar")
def desagendar_web(projeto_id: int, session: Session = Depends(get_session)):
	agendar.desagendar(session, projeto_id)
	return _redirect(f"/projetos/{projeto_id}")


def _sugestoes_agendar(session: Session) -> list[tuple[Projeto, Projeto, str]]:
	"""(plano, etapa liberada, horários) para planos sequenciais com etapa ainda não agendada."""
	sugestoes = []
	planos = session.exec(select(Projeto).where(Projeto.sequencial == True, Projeto.agenda_dias.is_not(None))).all()  # noqa: E712
	for pl in planos:
		if pl.status != StatusProjeto.ativo:
			continue
		etapa = agendar.proxima_para_agendar(session, pl.id)
		if etapa:
			sugestoes.append((pl, etapa, agendar.Horarios.de_projeto(pl).texto()))
	return sugestoes


@router.post("/remarcar/{item_id}", response_class=HTMLResponse)
def remarcar_item(request: Request, item_id: int, modo: str = "so", session: Session = Depends(get_session)):
	"""Remarca uma tarefa atrasada nos horários de estudo do plano.
	modo=so: só ela, no próximo espaço livre. modo=empurrar: ela e as seguintes da etapa,
	redistribuídas mantendo a ordem."""
	item = get_or_404(session, Item, item_id)
	h = agendar.horarios_herdados(session, item.projeto_id)[0] if item.projeto_id else None
	if h is None:  # sem horários guardados: abre a tela certa para escolher
		destino = f"/projetos/{item.projeto_id}/agendar" if item.projeto_id else f"/itens/{item_id}"
		resp = HTMLResponse("")
		resp.headers["HX-Redirect"] = destino
		return resp
	empurrar = modo == "empurrar"
	ag = agendar.planejar(
		session, item.projeto_id, h, remarcar=True, empurrar=empurrar,
		so_itens=None if empurrar else {item_id}, desde_item=item_id if empurrar else None,
	)
	if ag.encaixes:
		primeiro = next((e for e in ag.encaixes if e.item.id == item_id), ag.encaixes[0])
		titulo, quando = item.titulo, primeiro.inicio
		movidas = sum(1 for e in ag.encaixes if e.item.id != item_id and e.item.inicio != e.inicio)
		_, destino = agendar.horarios_herdados(session, item.projeto_id)
		agendar.aplicar(session, item.projeto_id, ag, guardar_em=destino)
		aviso = f"“{titulo}” remarcada para {_dia(quando)} às {_hora(quando)}"
		if empurrar:
			aviso += (
				f" (+{movidas} seguinte{'s' if movidas > 1 else ''} empurrada{'s' if movidas > 1 else ''})"
				if movidas else " (as seguintes já estavam depois, continuam no lugar)"
			)
	else:
		aviso = "Não encontrei horário livre: " + "; ".join(ag.avisos or ["confira os horários do plano"])
	ctx = _ctx_hoje(session, date.today())
	return render(request, "partials/hoje_listas.html", session, aviso_remarcar=aviso, **ctx)
