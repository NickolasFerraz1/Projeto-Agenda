"""API do importador de planejamento (usada pela tela "Importar plano" e pelo plugin
"Agenda" do Obsidian, em obsidian/agenda: mesma prévia e mesma importação)."""
from dataclasses import asdict
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models import Area, Projeto, StatusItem, StatusProjeto, TipoItem
from app.services import plano as svc
from app.services.progresso import Arvore, chave_irmaos

router = APIRouter(prefix="/api/planos", tags=["planejamento"])


class PlanoIn(BaseModel):
	texto: str = Field(min_length=1, max_length=500_000)


def _executar(dados: PlanoIn, session: Session, simular: bool) -> dict:
	try:
		rel = svc.aplicar(session, svc.ler(dados.texto), simular=simular)
	except svc.ErroPlano as exc:
		raise HTTPException(422, str(exc)) from exc
	out = asdict(rel)
	if simular:
		out["projeto_id"] = None
	return out


@router.get("/modelo", response_class=PlainTextResponse)
def modelo():
	return svc.MODELO


@router.get("/formato", response_class=PlainTextResponse)
def formato():
	return svc.FORMATO


@router.get("/prompt", response_class=PlainTextResponse)
def prompt(modo: str = "criar"):
	"""modo=criar (novo plano) ou modo=converter (reescrever um plano existente no formato)."""
	return svc.prompt(modo)


@router.post("/previa")
def previa(dados: PlanoIn, session: Session = Depends(get_session)):
	"""Simula a importação e devolve o que seria criado/atualizado (não grava nada)."""
	return _executar(dados, session, simular=True)


@router.post("/importar")
def importar(dados: PlanoIn, session: Session = Depends(get_session)):
	return _executar(dados, session, simular=False)


# ---------------------------------------------------------------------------
# Andamento (espelho: "Piano · Semana 2 · 1 de 2")
# ---------------------------------------------------------------------------
class ProximaOut(BaseModel):
	titulo: str
	inicio: datetime | None


class AndamentoOut(BaseModel):
	projeto_id: int
	nome: str
	area_cor: str
	etapa_id: int
	etapa: str | None  # caminho a partir da raiz ("Semana 2", "Fase 1 › Semana 2"); None = a própria raiz
	tarefas_feitas: int
	tarefas_total: int
	etapa_progresso: float | None
	plano_progresso: float | None
	proxima: ProximaOut | None  # 1ª tarefa em aberto da etapa, na ordem do plano


def _tem_tarefa_aberta(arv: Arvore, projeto: Projeto) -> bool:
	return any(i.status != StatusItem.concluido and i.tipo != TipoItem.habito for i in arv.itens.get(projeto.id, []))


def _etapa_atual(arv: Arvore, projeto: Projeto, travados: set[int], raiz: bool = True) -> Projeto:
	"""A etapa onde o plano está: a 1ª em aberto e liberada; só desce para as de dentro
	(### dentro de ##) quando a de fora não tem mais tarefa própria em aberto."""
	if not raiz and _tem_tarefa_aberta(arv, projeto):
		return projeto
	for f in arv.filhos.get(projeto.id, []):
		if f.id in travados or f.status in (StatusProjeto.pausado, StatusProjeto.arquivado) or arv.concluido(f.id):
			continue
		return _etapa_atual(arv, f, travados, raiz=False)
	return projeto


@router.get("/andamento", response_model=list[AndamentoOut])
def andamento(limite: int = Query(3, ge=1, le=20), session: Session = Depends(get_session)):
	"""Planos (projetos de topo com etapas) ativos e não concluídos, com a etapa atual.

	Ordem: o que tem tarefa marcada mais cedo (de hoje em diante) primeiro; sem data, por último
	(prioridade, depois nome)."""
	arv = Arvore.carregar(session)
	travados = arv.bloqueados()
	cores = {a.id: a.cor for a in session.exec(select(Area)).all()}
	hoje = datetime.combine(date.today(), time())
	saida = []
	for raiz in arv.filhos.get(None, []):
		if raiz.status != StatusProjeto.ativo or not arv.filhos.get(raiz.id) or arv.concluido(raiz.id):
			continue
		etapa = _etapa_atual(arv, raiz, travados)
		tarefas = [i for i in sorted(arv.itens.get(etapa.id, []), key=chave_irmaos) if i.tipo != TipoItem.habito]
		abertas = [i for i in tarefas if i.status != StatusItem.concluido]
		ids = {raiz.id} | arv.descendentes(raiz.id)
		datas = [
			i.inicio for pid in ids for i in arv.itens.get(pid, [])
			if i.inicio and i.inicio >= hoje and i.status != StatusItem.concluido
		]
		caminho = [p.nome for p in arv.caminho(etapa.id)[1:]]
		saida.append((
			(not datas, min(datas) if datas else datetime.max, -raiz.prioridade.peso),
			AndamentoOut(
				projeto_id=raiz.id,
				nome=raiz.nome,
				area_cor=cores.get(raiz.area_id, "#888888"),
				etapa_id=etapa.id,
				etapa=" › ".join(caminho) or None,
				tarefas_feitas=len(tarefas) - len(abertas),
				tarefas_total=len(tarefas),
				etapa_progresso=arv.percentual(etapa.id),
				plano_progresso=arv.percentual(raiz.id),
				proxima=ProximaOut(titulo=abertas[0].titulo, inicio=abertas[0].inicio) if abertas else None,
			),
		))
	saida.sort(key=lambda par: par[0])  # estável: empates mantêm a ordem de chave_irmaos
	return [out for _, out in saida[:limite]]
