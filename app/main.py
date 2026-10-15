"""Projeto Agenda — app de tarefas (FastAPI + SQLite)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db
from app.routers import agenda, areas, itens, projetos


@asynccontextmanager
async def lifespan(app: FastAPI):
	if db.engine is None:  # os testes configuram o próprio engine
		db.init_engine()
	db.create_db()
	yield


app = FastAPI(title="Projeto Agenda", version="0.1.0", lifespan=lifespan)
app.include_router(areas.router)
app.include_router(projetos.router)
app.include_router(itens.router)
app.include_router(agenda.router)


@app.get("/api/saude", tags=["sistema"])
def saude():
	return {"ok": True}
