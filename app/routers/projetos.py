from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Area, Item, Projeto, StatusProjeto
from app.routers.common import apply_update, check_fk, get_or_404, item_out, projeto_out, replace_links
from app.schemas import ItemOut, ProjetoIn, ProjetoOut, ProjetoUpdate
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
