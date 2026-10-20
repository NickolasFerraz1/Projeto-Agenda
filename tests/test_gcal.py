"""Sincronização com o Google Agenda (com um cliente falso, sem rede)."""
import itertools

from sqlmodel import Session

from app import db
from app.services import gcal


class GoogleFalso:
	def __init__(self):
		self.eventos: dict[str, dict] = {}
		self.chamadas = []
		self._ids = itertools.count(1)

	def listar(self):
		return [{"id": i, **e} for i, e in self.eventos.items()]

	def criar(self, corpo):
		self.chamadas.append("criar")
		self.eventos[f"ev{next(self._ids)}"] = corpo

	def atualizar(self, event_id, corpo):
		self.chamadas.append("atualizar")
		self.eventos[event_id] = corpo

	def apagar(self, event_id):
		self.chamadas.append("apagar")
		self.eventos.pop(event_id, None)

	def por_chave(self):
		return {e["extendedProperties"]["private"]["chave"]: e for e in self.eventos.values()}


def _sync(g):
	with Session(db.engine) as s:
		return gcal.sincronizar(s, g)


def test_cria_atualiza_e_apaga(client, area_id):
	g = GoogleFalso()
	a = client.post("/api/itens", json={"titulo": "Reunião", "area_id": area_id, "prioridade": "critica",
		"inicio": "2026-10-20T10:00:00", "fim": "2026-10-20T11:00:00"}).json()
	client.post("/api/itens", json={"titulo": "Sem data", "area_id": area_id})  # não vai para o Google
	r = _sync(g)
	assert (r.criados, r.total) == (1, 1)
	ev = g.por_chave()[f"item:{a['id']}"]
	assert ev["summary"] == "Reunião" and ev["colorId"] == "11"
	assert ev["start"] == {"dateTime": "2026-10-20T10:00:00", "timeZone": "America/Sao_Paulo"}
	assert ev["end"]["dateTime"] == "2026-10-20T11:00:00"
	assert f"/itens/{a['id']}" in ev["description"]

	assert _sync(g).criados == 0 and g.chamadas == ["criar"]  # nada mudou: nenhuma chamada

	client.patch(f"/api/itens/{a['id']}", json={"titulo": "Reunião com cliente"})
	assert _sync(g).atualizados == 1
	assert g.por_chave()[f"item:{a['id']}"]["summary"] == "Reunião com cliente"

	client.patch(f"/api/itens/{a['id']}", json={"status": "concluido"})
	_sync(g)
	ev = g.por_chave()[f"item:{a['id']}"]
	assert ev["summary"] == "✓ Reunião com cliente" and ev["reminders"] == {"useDefault": False, "overrides": []}

	client.delete(f"/api/itens/{a['id']}")
	assert _sync(g).apagados == 1 and g.eventos == {}


def test_dia_inteiro_recorrente_prazo_e_duracao(client, area_id):
	g = GoogleFalso()
	client.post("/api/itens", json={"titulo": "Feriado", "area_id": area_id, "inicio": "2026-11-02T00:00:00", "dia_inteiro": True})
	aula = client.post("/api/itens", json={"titulo": "Aula", "area_id": area_id, "inicio": "2026-10-20T19:00:00",
		"fim": "2026-10-20T22:00:00", "recorrencia": "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261212T235959"}).json()
	entrega = client.post("/api/itens", json={"titulo": "Entrega", "area_id": area_id, "prazo": "2026-10-30T23:59:00"}).json()
	estudo = client.post("/api/itens", json={"titulo": "Estudo", "area_id": area_id, "inicio": "2026-10-21T19:00:00", "duracao_min": 45}).json()
	_sync(g)
	ev = g.por_chave()
	feriado = next(e for k, e in ev.items() if e["summary"] == "Feriado")
	assert feriado["start"] == {"date": "2026-11-02"} and feriado["end"] == {"date": "2026-11-03"}
	# UNTIL local 23:59:59 em São Paulo (UTC-3) = 02:59:59Z do dia seguinte
	assert ev[f"item:{aula['id']}"]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261213T025959Z"]
	prazo = ev[f"prazo:{entrega['id']}"]
	assert prazo["summary"] == "⏰ Prazo: Entrega" and prazo["start"] == {"date": "2026-10-30"}
	assert ev[f"item:{estudo['id']}"]["end"]["dateTime"] == "2026-10-21T19:45:00"  # usa a duração estimada
	client.patch(f"/api/itens/{entrega['id']}", json={"status": "concluido"})
	_sync(g)
	assert f"prazo:{entrega['id']}" not in g.por_chave()  # prazo de item concluído sai


def test_cancelado_sai_e_duplicado_e_limpo(client, area_id):
	g = GoogleFalso()
	i = client.post("/api/itens", json={"titulo": "X", "area_id": area_id, "inicio": "2026-10-20T10:00:00"}).json()
	_sync(g)
	copia = dict(next(iter(g.eventos.values())))
	g.eventos["duplicado"] = copia  # ex.: rodada interrompida no meio
	g.eventos["alheio"] = {"summary": "sem chave", "extendedProperties": {"private": {"origem": "agenda"}}}
	r = _sync(g)
	assert r.apagados == 2 and len(g.eventos) == 1
	client.patch(f"/api/itens/{i['id']}", json={"status": "cancelado"})
	_sync(g)
	assert g.eventos == {}


def test_erro_de_um_evento_nao_para_os_outros(client, area_id):
	class GoogleInstavel(GoogleFalso):
		def criar(self, corpo):
			if corpo["summary"] == "Quebra":
				raise RuntimeError("Google 400: inválido")
			super().criar(corpo)

	g = GoogleInstavel()
	client.post("/api/itens", json={"titulo": "Quebra", "area_id": area_id, "inicio": "2026-10-20T10:00:00"})
	client.post("/api/itens", json={"titulo": "Ok", "area_id": area_id, "inicio": "2026-10-20T11:00:00"})
	r = _sync(g)
	assert r.criados == 1 and len(r.erros) == 1 and "inválido" in r.erros[0]


def test_rodar_agora_e_status_na_tela(client, area_id, monkeypatch):
	g = GoogleFalso()
	monkeypatch.setattr(gcal, "_fabrica_cliente", lambda: g)
	monkeypatch.setattr(gcal.ESTADO, "configurado", True)
	client.post("/api/itens", json={"titulo": "Y", "area_id": area_id, "inicio": "2026-10-20T10:00:00"})
	r = client.post("/google/sincronizar", follow_redirects=False)
	assert r.status_code == 303 and len(g.eventos) == 1
	html = client.get("/areas").text
	assert "Última sincronização" in html and "1 eventos" in html
	assert client.get("/api/saude").json()["google"]["eventos"] == 1


def test_desligado_sem_configuracao(client):
	assert "Desligado" in client.get("/areas").text
	assert client.get("/api/saude").json()["google"]["configurado"] is False


def test_botao_htmx_devolve_cartao_e_toast(client, area_id, monkeypatch):
	g = GoogleFalso()
	monkeypatch.setattr(gcal, "_fabrica_cliente", lambda: g)
	monkeypatch.setattr(gcal.ESTADO, "configurado", True)
	client.post("/api/itens", json={"titulo": "Z", "area_id": area_id, "inicio": "2026-10-20T10:00:00"})
	r = client.post("/google/sincronizar", headers={"HX-Request": "true"})
	assert r.status_code == 200 and 'id="cartao-google"' in r.text and "<html" not in r.text
	assert "1 criados" in r.headers["HX-Trigger"]
	r = client.post("/google/sincronizar", headers={"HX-Request": "true"})
	assert "em dia" in r.headers["HX-Trigger"]


def test_dia_pulado_vira_exdate(client, area_id):
	g = GoogleFalso()
	aula = client.post("/api/itens", json={"titulo": "Aula", "area_id": area_id, "inicio": "2026-10-20T19:00:00",
		"recorrencia": "FREQ=WEEKLY;BYDAY=TU,TH"}).json()
	feriado = client.post("/api/itens", json={"titulo": "Yoga", "area_id": area_id, "inicio": "2026-10-20T00:00:00",
		"dia_inteiro": True, "recorrencia": "FREQ=DAILY"}).json()
	_sync(g)
	assert g.por_chave()[f"item:{aula['id']}"]["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TU,TH"]
	client.post(f"/pular/{aula['id']}?dia=2026-10-22")
	client.post(f"/pular/{aula['id']}?dia=2026-10-27")
	client.post(f"/pular/{feriado['id']}?dia=2026-10-21")
	r = _sync(g)
	assert r.atualizados == 2
	ev = g.por_chave()
	assert ev[f"item:{aula['id']}"]["recurrence"][1] == "EXDATE;TZID=America/Sao_Paulo:20261022T190000,20261027T190000"
	assert ev[f"item:{feriado['id']}"]["recurrence"][1] == "EXDATE;VALUE=DATE:20261021"
	client.post(f"/pular/{aula['id']}?dia=2026-10-22")  # desfaz um
	_sync(g)
	assert g.por_chave()[f"item:{aula['id']}"]["recurrence"][1].endswith(":20261027T190000")
