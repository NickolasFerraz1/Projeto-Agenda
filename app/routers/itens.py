from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Area, Item, Ocorrencia, Projeto, StatusItem, StatusOcorrencia, TipoItem
from app.routers.common import apply_update, check_fk, get_or_404, item_out, replace_links
from app.schemas import ItemIn, ItemOut, ItemUpdate, OcorrenciaIn, OcorrenciaOut
from app.services import agendar, recorrencia

router = APIRouter(prefix="/api/itens", tags=["itens"])


def _herdar_do_projeto(session: Session, campos: dict) -> None:
	"""Área e prioridade vêm do projeto quando não informadas."""
	projeto_id = campos.get("projeto_id")
	projeto = session.get(Projeto, projeto_id) if projeto_id else None
	if projeto_id and projeto is None:
		raise HTTPException(422, f"projeto_id: Projeto {projeto_id} não existe")
	if campos.get("area_id") is None:
		if projeto is None:
			raise HTTPException(422, "area_id é obrigatória para itens sem projeto")
		campos["area_id"] = projeto.area_id
	if campos.get("prioridade") is None:
		campos["prioridade"] = projeto.prioridade if projeto else "media"


@router.get("", response_model=list[ItemOut])
def listar(
	projeto_id: int | None = None,
	area_id: int | None = None,
	status: StatusItem | None = None,
	tipo: TipoItem | None = None,
	sem_data: bool = False,
	session: Session = Depends(get_session),
):
	query = select(Item)
	if projeto_id is not None:
		query = query.where(Item.projeto_id == projeto_id)
	if area_id is not None:
		query = query.where(Item.area_id == area_id)
	if status is not None:
		query = query.where(Item.status == status)
	if tipo is not None:
		query = query.where(Item.tipo == tipo)
	if sem_data:
		query = query.where(Item.inicio.is_(None))
	itens = session.exec(query).all()
	itens = sorted(itens, key=lambda i: (-i.prioridade.peso, i.prazo or datetime.max, i.inicio or datetime.max))
	return [item_out(session, i) for i in itens]


@router.post("", response_model=ItemOut, status_code=201)
def criar(dados: ItemIn, session: Session = Depends(get_session)):
	campos = dados.model_dump(exclude={"links"})
	_herdar_do_projeto(session, campos)
	check_fk(session, Area, campos["area_id"], "area_id")
	campos = {k: v for k, v in campos.items() if v is not None}
	item = Item(**campos)
	session.add(item)
	session.flush()
	replace_links(session, dados.links, item_id=item.id)
	session.commit()
	session.refresh(item)
	return item_out(session, item)


@router.get("/{item_id}", response_model=ItemOut)
def obter(item_id: int, session: Session = Depends(get_session)):
	return item_out(session, get_or_404(session, Item, item_id))


@router.patch("/{item_id}", response_model=ItemOut)
def atualizar(item_id: int, dados: ItemUpdate, session: Session = Depends(get_session)):
	item = get_or_404(session, Item, item_id)
	estava_concluido = item.status == StatusItem.concluido
	campos = dados.model_dump(exclude_unset=True, exclude={"links"})
	check_fk(session, Projeto, campos.get("projeto_id"), "projeto_id")
	check_fk(session, Area, campos.get("area_id"), "area_id")
	apply_update(item, campos)
	# Validações que dependem do estado final (campos antigos + novos)
	if item.inicio and item.fim and item.fim < item.inicio:
		raise HTTPException(422, "fim não pode ser antes do início")
	if item.recorrencia and not item.inicio:
		raise HTTPException(422, "item recorrente precisa de início")
	if dados.links is not None:
		replace_links(session, dados.links, item_id=item.id)
	session.commit()
	session.refresh(item)
	if not estava_concluido and item.status == StatusItem.concluido:
		agendar.ao_concluir(session, item)  # plano sequencial: pode agendar a próxima etapa
	return item_out(session, item)


@router.delete("/{item_id}", status_code=204)
def excluir(item_id: int, session: Session = Depends(get_session)):
	session.delete(get_or_404(session, Item, item_id))
	session.commit()


# ---------- Ocorrências (itens recorrentes) ----------
@router.get("/{item_id}/ocorrencias", response_model=list[OcorrenciaOut])
def listar_ocorrencias(item_id: int, de: date | None = None, ate: date | None = None, session: Session = Depends(get_session)):
	get_or_404(session, Item, item_id)
	query = select(Ocorrencia).where(Ocorrencia.item_id == item_id)
	if de:
		query = query.where(Ocorrencia.data >= de)
	if ate:
		query = query.where(Ocorrencia.data <= ate)
	return session.exec(query.order_by(Ocorrencia.data)).all()


@router.put("/{item_id}/ocorrencias", response_model=OcorrenciaOut)
def marcar_ocorrencia(item_id: int, dados: OcorrenciaIn, session: Session = Depends(get_session)):
	"""Marca o dia como concluído/pulado (cria ou atualiza o registro do dia)."""
	item = get_or_404(session, Item, item_id)
	if not item.recorrencia:
		raise HTTPException(422, "ocorrências só existem para itens recorrentes; use o status do item")
	if not recorrencia.ocorrencias(item.recorrencia, item.inicio, dados.data, dados.data):
		raise HTTPException(422, f"o item não acontece em {dados.data.isoformat()}")
	oc = session.exec(select(Ocorrencia).where(Ocorrencia.item_id == item_id, Ocorrencia.data == dados.data)).first()
	if oc is None:
		oc = Ocorrencia(item_id=item_id, **dados.model_dump())
		session.add(oc)
	else:
		oc.status, oc.nota = dados.status, dados.nota
	session.commit()
	session.refresh(oc)
	return oc


@router.delete("/{item_id}/ocorrencias/{dia}", status_code=204)
def desmarcar_ocorrencia(item_id: int, dia: date, session: Session = Depends(get_session)):
	oc = session.exec(select(Ocorrencia).where(Ocorrencia.item_id == item_id, Ocorrencia.data == dia)).first()
	if oc is None:
		raise HTTPException(404, "nada registrado nesse dia")
	if oc.inicio:  # ocorrência movida: mantém o horário novo, só volta a "a fazer"
		oc.status = StatusOcorrencia.a_fazer
	else:
		session.delete(oc)
	session.commit()
