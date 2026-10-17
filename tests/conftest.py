import pytest
from fastapi.testclient import TestClient

from app import db


@pytest.fixture()
def client(monkeypatch):
	from app import config

	monkeypatch.setattr(config, "GCAL_ID", "")  # testes nunca falam com o Google de verdade
	db.init_engine("sqlite://")  # banco em memória, novo a cada teste
	from app.main import app

	with TestClient(app) as c:
		yield c
	db.engine = None


@pytest.fixture()
def area_id(client):
	return next(a["id"] for a in client.get("/api/areas").json() if a["nome"] == "Estudo")
