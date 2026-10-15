import pytest
from fastapi.testclient import TestClient

from app import db


@pytest.fixture()
def client():
	db.init_engine("sqlite://")  # banco em memória, novo a cada teste
	from app.main import app

	with TestClient(app) as c:
		yield c
	db.engine = None


@pytest.fixture()
def area_id(client):
	return next(a["id"] for a in client.get("/api/areas").json() if a["nome"] == "Estudo")
