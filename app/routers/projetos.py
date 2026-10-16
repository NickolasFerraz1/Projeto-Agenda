from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Area, Item, Projeto, StatusProjeto
from app.routers.common import apply_update, check_fk, get_or_404, item_out, projeto_out, replace_links
from app.schemas import AgendarIn, ItemOut, ProjetoIn, ProjetoOut, ProjetoUpdate
from app.services import agendar as svc_agendar
from app.services.progresso import Arvore, chave_irmaos

router = APIRouter(prefix="/api/projetos", tags=["projetos"])


@router.get("", response_model=list[ProjetoOut])
def listar(
	area_id: int | None = None,
	status: StatusProjeto | None = None,
	pai_id: int | None = None,
	raiz: bool = False,  # só projetos de topo (sem pai)
	session: Session = Depends(get_session),
):
	query = select(Projeto)
	if area_id is not None:
		query = query.where(Projeto.area_id == area_id)
	if status is not None:
		query = query.where(Projeto.status == status)
	if pai_id is not None:
		query = query.where(Projeto.pai_id == pai_id)
	elif raiz:
		query = query.where(Projeto.pai_id.is_(None))
	projetos = session.exec(query).all()
	if pai_id is not None:  # subprojetos: ordem definida (ordem, nome natural)
		projetos = sorted(projetos, key=chave_irmaos)
	else:  # topo: prioridade, depois nome
		projetos = sorted(projetos, key=lambda p: (-p.prioridade.peso, chave_irmaos(p)))
	arv = Arvore.carregar(session)
	return [projeto_out(session, p, arv) for p in projetos]


def _herdar_do_pai(session: Session, campos: dict) -> None:
	pai = session.get(Projeto, campos["pai_id"]) if campos.get("pai_id") else None
	if campos.get("pai_id") and pai is None:
		raise HTTPException(422, f"pai_id: Projeto {campos['pai_id']} não existe")
	if campos.get("area_id") is None:
		if pai is None:
			raise HTTPException(422, "area_id é obrigatória para projetos sem pai")
		campos["area_id"] = pai.area_id
	if campos.get("prioridade") is None:
		campos["prioridade"] = pai.prioridade if pai else "media"


@router.post("", response_model=ProjetoOut, status_code=201)
def criar(dados: ProjetoIn, session: Session = Depends(get_session)):
	campos = dados.model_dump(exclude={"links"})
	_herdar_do_pai(session, campos)
	check_fk(session, Area, campos["area_id"], "area_id")
	projeto = Projeto(**{k: v for k, v in campos.items() if v is not None})
	session.add(projeto)
	session.flush()
	replace_links(session, dados.links, projeto_id=projeto.id)
	session.commit()
	session.refresh(projeto)
	return projeto_out(session, projeto)


@router.get("/{projeto_id}", response_model=ProjetoOut)
def obter(projeto_id: int, session: Session = Depends(get_session)):
	return projeto_out(session, get_or_404(session, Projeto, projeto_id))


@router.get("/{projeto_id}/itens", response_model=list[ItemOut])
def itens(projeto_id: int, session: Session = Depends(get_session)):
	"""Itens diretos do projeto (os dos subprojetos ficam em cada subprojeto)."""
	get_or_404(session, Projeto, projeto_id)
	itens = session.exec(select(Item).where(Item.projeto_id == projeto_id)).all()
	return [item_out(session, i) for i in sorted(itens, key=chave_irmaos)]


@router.patch("/{projeto_id}", response_model=ProjetoOut)
def atualizar(projeto_id: int, dados: ProjetoUpdate, session: Session = Depends(get_session)):
	projeto = get_or_404(session, Projeto, projeto_id)
	campos = dados.model_dump(exclude_unset=True, exclude={"links"})
	check_fk(session, Area, campos.get("area_id"), "area_id")
	if campos.get("pai_id") is not None:
		check_fk(session, Projeto, campos["pai_id"], "pai_id")
		if campos["pai_id"] == projeto_id or campos["pai_id"] in Arvore.carregar(session).descendentes(projeto_id):
			raise HTTPException(422, "um projeto não pode ficar dentro dele mesmo ou de um subprojeto seu")
	apply_update(projeto, campos)
	if dados.links is not None:
		replace_links(session, dados.links, projeto_id=projeto.id)
	session.commit()
	session.refresh(projeto)
	return projeto_out(session, projeto)


@router.delete("/{projeto_id}", status_code=204)
def excluir(projeto_id: int, session: Session = Depends(get_session)):
	"""Exclui o projeto. Subprojetos e itens sobem um nível (vão para o pai, ou ficam sem projeto)."""
	projeto = get_or_404(session, Projeto, projeto_id)
	for filho in session.exec(select(Projeto).where(Projeto.pai_id == projeto_id)).all():
		filho.pai_id = projeto.pai_id
	for item in session.exec(select(Item).where(Item.projeto_id == projeto_id)).all():
		item.projeto_id = projeto.pai_id
	session.flush()
	session.delete(projeto)
	session.commit()


@router.post("/{projeto_id}/agendar")
def agendar(projeto_id: int, dados: AgendarIn, session: Session = Depends(get_session)):
	"""Distribui as tarefas em aberto (sem data; com `remarcar`, as atrasadas; com `empurrar`,
	também as já marcadas no futuro) do projeto e das subetapas nos horários informados.
	`simular=true` só devolve a prévia."""
	from datetime import time

	get_or_404(session, Projeto, projeto_id)
	horarios = svc_agendar.Horarios(dados.dias, time.fromisoformat(dados.hora), dados.minutos)
	ag = svc_agendar.planejar(session, projeto_id, horarios, dados.a_partir, dados.remarcar, empurrar=dados.empurrar)
	resposta = {
		"horarios": horarios.texto(),
		"encaixes": [
			{"item_id": e.item.id, "titulo": e.item.titulo, "etapa": e.caminho, "inicio": e.inicio, "fim": e.fim, "estourou": e.estourou}
			for e in ag.encaixes
		],
		"sobras": [{"item_id": i.id, "titulo": i.titulo} for i in ag.sobras],
		"avisos": ag.avisos,
		"aplicado": False,
	}
	if not dados.simular and ag.encaixes:
		_, destino = svc_agendar.horarios_herdados(session, projeto_id)
		svc_agendar.aplicar(session, projeto_id, ag, guardar_em=destino)
		resposta["aplicado"] = True
	if dados.auto is not None and not dados.simular:
		_, destino = svc_agendar.horarios_herdados(session, projeto_id)
		plano = session.get(Projeto, destino)
		plano.agenda_auto = dados.auto
		session.commit()
	return resposta


@router.post("/{projeto_id}/desagendar")
def desagendar(projeto_id: int, session: Session = Depends(get_session)):
	"""Tira a data das tarefas em aberto (de hoje em diante) do projeto e das subetapas."""
	get_or_404(session, Projeto, projeto_id)
	return {"removidos": svc_agendar.desagendar(session, projeto_id)}
