"""Projeto Agenda — app de tarefas (FastAPI + SQLite)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.routers import agenda, areas, itens, planos, projetos, web


@asynccontextmanager
async def lifespan(app: FastAPI):
	if db.engine is None:  # os testes configuram o próprio engine
		db.init_engine()
	db.create_db()
	yield


app = FastAPI(title="Projeto Agenda", version="0.3.0", lifespan=lifespan)
app.include_router(areas.router)
app.include_router(projetos.router)
app.include_router(itens.router)
app.include_router(agenda.router)
app.include_router(planos.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=config.ROOT / "app" / "static"), name="static")


@app.get("/api/saude", tags=["sistema"])
def saude():
	return {"ok": True}
