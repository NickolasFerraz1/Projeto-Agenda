"""Cálculo do percentual de progresso de projetos e itens."""
from sqlmodel import Session, func, select

from app.models import Item, ProgressoModo, StatusItem


def percentual(obj, session: Session | None = None) -> float | None:
	"""Percentual 0–100 conforme o modo, ou None quando não se aplica."""
	modo = obj.progresso_modo
	if modo == ProgressoModo.manual:
		return obj.progresso_manual
	if modo == ProgressoModo.quantidade:
		if not obj.progresso_total:
			return None
		return round(min(100.0, 100.0 * (obj.progresso_atual or 0) / obj.progresso_total), 1)
	if modo == ProgressoModo.itens and session is not None and getattr(obj, "id", None):
		return percentual_por_itens(obj.id, session)
	return None


def percentual_por_itens(projeto_id: int, session: Session) -> float | None:
	"""Itens concluídos / itens válidos do projeto (ignora cancelados e recorrentes/hábitos)."""
	base = select(func.count()).select_from(Item).where(
		Item.projeto_id == projeto_id,
		Item.status != StatusItem.cancelado,
		Item.recorrencia.is_(None),
	)
	total = session.exec(base).one()
	if not total:
		return None
	feitos = session.exec(base.where(Item.status == StatusItem.concluido)).one()
	return round(100.0 * feitos / total, 1)
