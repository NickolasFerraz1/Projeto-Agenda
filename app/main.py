"""Projeto Agenda — app de tarefas (FastAPI + SQLite)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.services import gcal
from app.routers import agenda, areas, itens, planos, projetos, web


@asynccontextmanager
async def lifespan(app: FastAPI):
	if db.engine is None:  # os testes configuram o próprio engine
		db.init_engine()
	db.create_db()
	gcal.iniciar()  # sincronização com o Google Agenda (só se configurada)
	yield
	gcal.parar()


app = FastAPI(title="Projeto Agenda", version="0.3.0", lifespan=lifespan)
app.include_router(areas.router)
app.include_router(projetos.router)
app.include_router(itens.router)
app.include_router(agenda.router)
app.include_router(planos.router)
app.include_router(web.router)
app.mount("/static", StaticFiles(directory=config.ROOT / "app" / "static"), name="static")


@app.middleware("http")
async def versao_nova(request: Request, call_next):
	"""A navegação rápida (hx-boost) troca só o corpo da página: CSS/JS ficam os da versão em que
	a janela abriu. Se o app foi atualizado no meio, manda o navegador recarregar a página inteira."""
	resposta = await call_next(request)
	versao = request.headers.get("X-Agenda-Versao")
	if versao and versao != config.ASSET_VERSION and request.headers.get("HX-Request"):
		resposta.headers["HX-Refresh"] = "true"
	return resposta


@app.middleware("http")
async def avisar_google(request: Request, call_next):
	"""Depois de qualquer alteração bem-sucedida, antecipa a sincronização com o Google."""
	resposta = await call_next(request)
	if request.method in ("POST", "PUT", "PATCH", "DELETE") and resposta.status_code < 400:
		gcal.avisar_mudanca()
	return resposta


@app.get("/api/saude", tags=["sistema"])
def saude():
	e = gcal.ESTADO
	return {
		"ok": True,
		"google": {
			"configurado": e.configurado,
			"ultima": e.ultima,
			"erro": e.erro,
			"eventos": e.resultado.total if e.resultado else None,
		},
	}
