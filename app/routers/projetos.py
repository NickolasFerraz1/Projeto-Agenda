from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Area, Item, Projeto, StatusProjeto
from app.routers.common import apply_update, check_fk, get_or_404, item_out, projeto_out, replace_links
from app.schemas import ItemOut, ProjetoIn, ProjetoOut, ProjetoUpdate

router = APIRouter(prefix="/api/projetos", tags=["projetos"])


@router.get("", response_model=list[ProjetoOut])
def listar(
	area_id: int | None = None,
	status: StatusProjeto | None = None,
	session: Session = Depends(get_session),
):
	query = select(Projeto)
	if area_id is not None:
		query = query.where(Projeto.area_id == area_id)
	if status is not None:
		query = query.where(Projeto.status == status)
	projetos = session.exec(query).all()
	projetos = sorted(projetos, key=lambda p: (-p.prioridade.peso, p.nome.lower()))
	return [projeto_out(session, p) for p in projetos]


@router.post("", response_model=ProjetoOut, status_code=201)
def criar(dados: ProjetoIn, session: Session = Depends(get_session)):
	check_fk(session, Area, dados.area_id, "area_id")
	campos = dados.model_dump(exclude={"links"}, exclude_none=True)
	projeto = Projeto(**campos)
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
	get_or_404(session, Projeto, projeto_id)
	itens = session.exec(select(Item).where(Item.projeto_id == projeto_id)).all()
	return [item_out(session, i) for i in itens]


@router.patch("/{projeto_id}", response_model=ProjetoOut)
def atualizar(projeto_id: int, dados: ProjetoUpdate, session: Session = Depends(get_session)):
	projeto = get_or_404(session, Projeto, projeto_id)
	campos = dados.model_dump(exclude_unset=True, exclude={"links"})
	check_fk(session, Area, campos.get("area_id"), "area_id")
	apply_update(projeto, campos)
	if dados.links is not None:
		replace_links(session, dados.links, projeto_id=projeto.id)
	session.commit()
	session.refresh(projeto)
	return projeto_out(session, projeto)


@router.delete("/{projeto_id}", status_code=204)
def excluir(projeto_id: int, session: Session = Depends(get_session)):
	"""Exclui o projeto; os itens ficam sem projeto (não são apagados)."""
	projeto = get_or_404(session, Projeto, projeto_id)
	session.delete(projeto)
	session.commit()
