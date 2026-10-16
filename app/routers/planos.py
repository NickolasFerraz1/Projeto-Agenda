"""API do importador de planejamento (usada pela tela "Importar plano" e, no futuro, pelo
botão "Enviar para a Agenda" dentro do Obsidian)."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.services import plano as svc

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
