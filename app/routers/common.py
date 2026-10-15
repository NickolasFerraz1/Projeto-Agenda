"""Funções compartilhadas pelos routers."""
from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Area, Item, Link, Projeto
from app.schemas import ItemOut, LinkIn, ProjetoOut
from app.services.progresso import percentual


def get_or_404(session: Session, model, obj_id: int):
	obj = session.get(model, obj_id)
	if obj is None:
		raise HTTPException(404, f"{model.__name__} {obj_id} não encontrado")
	return obj


def check_fk(session: Session, model, obj_id: int | None, campo: str) -> None:
	if obj_id is not None and session.get(model, obj_id) is None:
		raise HTTPException(422, f"{campo}: {model.__name__} {obj_id} não existe")


def replace_links(session: Session, links: list[LinkIn], *, item_id=None, projeto_id=None) -> None:
	cond = Link.item_id == item_id if item_id is not None else Link.projeto_id == projeto_id
	for old in session.exec(select(Link).where(cond)).all():
		session.delete(old)
	for link in links:
		session.add(Link(item_id=item_id, projeto_id=projeto_id, **link.model_dump()))


def links_of(session: Session, *, item_id=None, projeto_id=None) -> list[Link]:
	cond = Link.item_id == item_id if item_id is not None else Link.projeto_id == projeto_id
	return list(session.exec(select(Link).where(cond).order_by(Link.id)).all())


def item_out(session: Session, item: Item) -> ItemOut:
	return ItemOut(
		**item.model_dump(),
		progresso=percentual(item, session),
		links=[l.model_dump() for l in links_of(session, item_id=item.id)],
	)


def projeto_out(session: Session, projeto: Projeto) -> ProjetoOut:
	return ProjetoOut(
		**projeto.model_dump(),
		progresso=percentual(projeto, session),
		links=[l.model_dump() for l in links_of(session, projeto_id=projeto.id)],
	)


def apply_update(obj, data: dict) -> None:
	for key, value in data.items():
		setattr(obj, key, value)
	if hasattr(obj, "atualizado_em"):
		obj.atualizado_em = datetime.now()


__all__ = ["Area", "get_or_404", "check_fk", "replace_links", "item_out", "projeto_out", "apply_update"]
