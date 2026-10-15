from datetime import date


def _criar(client, **campos):
	r = client.post("/api/itens", json=campos)
	assert r.status_code == 201, r.text
	return r.json()


def test_recorrencia_invalida(client, area_id):
	r = client.post("/api/itens", json={"titulo": "X", "area_id": area_id, "inicio": "2026-10-19T19:00", "recorrencia": "FREQ=TODO_DIA"})
	assert r.status_code == 422


def test_recorrente_precisa_de_inicio(client, area_id):
	r = client.post("/api/itens", json={"titulo": "X", "area_id": area_id, "recorrencia": "FREQ=DAILY"})
	assert r.status_code == 422


def test_agenda_expande_recorrencia(client, area_id):
	# Aulas terça e quinta, 19h–22h, a partir de 19/10/2026 (segunda)
	_criar(client, titulo="Aula FIAP", tipo="aula", area_id=area_id, inicio="2026-10-19T19:00", fim="2026-10-19T22:00",
		recorrencia="FREQ=WEEKLY;BYDAY=TU,TH")
	entradas = client.get("/api/agenda", params={"de": "2026-10-19", "ate": "2026-10-25"}).json()
	assert [e["data"] for e in entradas] == ["2026-10-20", "2026-10-22"]
	assert entradas[0]["inicio"] == "2026-10-20T19:00:00"
	assert entradas[0]["fim"] == "2026-10-20T22:00:00"
	assert all(e["recorrente"] and e["status"] == "a_fazer" for e in entradas)


def test_ocorrencia_marca_so_o_dia(client, area_id):
	academia = _criar(client, titulo="Academia", tipo="habito", area_id=area_id, inicio="2026-10-19T07:00", recorrencia="FREQ=DAILY")
	r = client.put(f"/api/itens/{academia['id']}/ocorrencias", json={"data": "2026-10-20", "status": "concluido", "nota": "pernas"})
	assert r.status_code == 200
	entradas = client.get("/api/agenda", params={"de": "2026-10-19", "ate": "2026-10-21"}).json()
	assert {e["data"]: e["status"] for e in entradas} == {"2026-10-19": "a_fazer", "2026-10-20": "concluido", "2026-10-21": "a_fazer"}
	# Desfazer
	assert client.delete(f"/api/itens/{academia['id']}/ocorrencias/2026-10-20").status_code == 204


def test_ocorrencia_em_dia_sem_aula(client, area_id):
	aula = _criar(client, titulo="Aula", area_id=area_id, inicio="2026-10-19T19:00", recorrencia="FREQ=WEEKLY;BYDAY=TU")
	r = client.put(f"/api/itens/{aula['id']}/ocorrencias", json={"data": "2026-10-21"})  # quarta
	assert r.status_code == 422


def test_ordem_horario_e_prioridade(client, area_id):
	_criar(client, titulo="Jogar FIFA", area_id=area_id, prioridade="baixa", inicio="2026-10-20T20:00")
	_criar(client, titulo="Entrega cliente", area_id=area_id, prioridade="critica", inicio="2026-10-20T20:00")
	_criar(client, titulo="Reunião", area_id=area_id, inicio="2026-10-20T09:00")
	_criar(client, titulo="Feriado", area_id=area_id, inicio="2026-10-20T00:00", dia_inteiro=True)
	titulos = [e["titulo"] for e in client.get("/api/agenda", params={"de": "2026-10-20", "ate": "2026-10-20"}).json()]
	assert titulos == ["Feriado", "Reunião", "Entrega cliente", "Jogar FIFA"]


def test_prazo_aparece_na_agenda(client, area_id):
	_criar(client, titulo="Entregar trabalho", area_id=area_id, prazo="2026-10-23T23:59")
	entradas = client.get("/api/agenda", params={"de": "2026-10-23", "ate": "2026-10-23"}).json()
	assert entradas[0]["tipo_entrada"] == "prazo"


def test_hoje(client, area_id):
	hoje = date(2026, 10, 20)
	_criar(client, titulo="Ontem não feito", area_id=area_id, inicio="2026-10-19T10:00")
	_criar(client, titulo="Ontem feito", area_id=area_id, inicio="2026-10-19T11:00", status="concluido")
	_criar(client, titulo="Hoje", area_id=area_id, inicio="2026-10-20T15:00")
	_criar(client, titulo="Sem data baixa", area_id=area_id, prioridade="baixa")
	_criar(client, titulo="Sem data crítica", area_id=area_id, prioridade="critica")
	r = client.get("/api/hoje", params={"dia": hoje.isoformat()}).json()
	assert [e["titulo"] for e in r["agenda"]] == ["Hoje"]
	assert [i["titulo"] for i in r["atrasados"]] == ["Ontem não feito"]
	assert [i["titulo"] for i in r["pendencias"]] == ["Sem data crítica", "Sem data baixa"]


def test_intervalo_invalido(client):
	assert client.get("/api/agenda", params={"de": "2026-10-20", "ate": "2026-10-19"}).status_code == 422
