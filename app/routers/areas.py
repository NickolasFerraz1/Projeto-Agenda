from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Area, Item, Projeto
from app.routers.common import apply_update, get_or_404
from app.schemas import AreaIn, AreaOut, AreaUpdate

router = APIRouter(prefix="/api/areas", tags=["áreas"])


@router.get("", response_model=list[AreaOut])
def listar(session: Session = Depends(get_session)):
	return session.exec(select(Area).order_by(Area.nome)).all()


@router.post("", response_model=AreaOut, status_code=201)
def criar(dados: AreaIn, session: Session = Depends(get_session)):
	if session.exec(select(Area).where(Area.nome == dados.nome)).first():
		raise HTTPException(409, f"já existe a área {dados.nome!r}")
	area = Area(**dados.model_dump())
	session.add(area)
	session.commit()
	session.refresh(area)
	return area


@router.patch("/{area_id}", response_model=AreaOut)
def atualizar(area_id: int, dados: AreaUpdate, session: Session = Depends(get_session)):
	area = get_or_404(session, Area, area_id)
	apply_update(area, dados.model_dump(exclude_unset=True))
	session.commit()
	session.refresh(area)
	return area


@router.delete("/{area_id}", status_code=204)
def excluir(area_id: int, session: Session = Depends(get_session)):
	area = get_or_404(session, Area, area_id)
	em_uso = session.exec(select(Projeto.id).where(Projeto.area_id == area_id)).first() or session.exec(
		select(Item.id).where(Item.area_id == area_id)
	).first()
	if em_uso:
		raise HTTPException(409, "área em uso por projetos ou itens; mova-os antes de excluir")
	session.delete(area)
	session.commit()
