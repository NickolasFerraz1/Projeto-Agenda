"""Interface web: páginas, captura rápida, marcar feito e formulários."""
from datetime import date

from app.services import recorrencia

HOJE = date.today()


def test_paginas_abrem(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Curso", "area_id": area_id}).json()
	i = client.post("/api/itens", json={"titulo": "Aula 1", "projeto_id": p["id"]}).json()
	for url in ["/", "/semana", "/projetos", f"/projetos/{p['id']}", f"/projetos/{p['id']}/editar",
				"/projetos/novo", "/itens/novo", f"/itens/{i['id']}", "/areas", "/offline"]:
		r = client.get(url)
		assert r.status_code == 200, url
		assert "<html" in r.text


def test_pwa(client):
	assert client.get("/manifest.webmanifest").json()["display"] == "standalone"
	sw = client.get("/sw.js")
	assert sw.headers["content-type"].startswith("application/javascript")
	assert sw.headers["service-worker-allowed"] == "/"
	assert client.get("/static/app.css").status_code == 200


def test_captura_rapida(client, area_id):
	r = client.post("/captura", data={"titulo": "Comprar fita", "area_id": area_id, "quando": ""}, headers={"HX-Request": "true"})
	assert r.status_code == 200 and 'id="hoje-conteudo"' in r.text and "Comprar fita" in r.text
	client.post("/captura", data={"titulo": "Ligar pro técnico", "area_id": area_id, "quando": "hoje", "hora": "15:30"})
	hoje = client.get("/api/hoje").json()
	assert [e["titulo"] for e in hoje["agenda"]] == ["Ligar pro técnico"]
	assert hoje["agenda"][0]["inicio"].endswith("15:30:00")
	assert [i["titulo"] for i in hoje["pendencias"]] == ["Comprar fita"]


def test_captura_sem_titulo_mostra_erro(client, area_id):
	r = client.post("/captura", data={"titulo": "", "area_id": area_id}, headers={"HX-Request": "true"})
	assert r.status_code == 200 and 'class="erros"' in r.text


def test_alternar_item_e_ocorrencia(client, area_id):
	unico = client.post("/api/itens", json={"titulo": "Tarefa", "area_id": area_id}).json()
	r = client.post(f"/alternar/{unico['id']}")
	assert "feito" in r.text and client.get(f"/api/itens/{unico['id']}").json()["status"] == "concluido"
	client.post(f"/alternar/{unico['id']}")
	assert client.get(f"/api/itens/{unico['id']}").json()["status"] == "a_fazer"

	inicio = f"{HOJE.isoformat()}T07:00:00"
	hab = client.post("/api/itens", json={"titulo": "Academia", "area_id": area_id, "inicio": inicio, "recorrencia": "FREQ=DAILY"}).json()
	r = client.post(f"/alternar/{hab['id']}?tipo=agendado&dia={HOJE.isoformat()}")
	assert "linha-item feito" in r.text
	ocs = client.get(f"/api/itens/{hab['id']}/ocorrencias").json()
	assert [o["data"] for o in ocs] == [HOJE.isoformat()]
	assert client.get(f"/api/itens/{hab['id']}").json()["status"] == "a_fazer"  # a série continua aberta
	client.post(f"/alternar/{hab['id']}?tipo=agendado&dia={HOJE.isoformat()}")
	assert client.get(f"/api/itens/{hab['id']}/ocorrencias").json() == []


def test_form_item_cria_com_recorrencia_e_edita(client, area_id):
	form = {
		"titulo": "Pós — aula", "tipo": "aula", "area_id": area_id, "prioridade": "alta", "status": "a_fazer",
		"data": "2026-10-20", "hora_inicio": "19:00", "hora_fim": "22:00",
		"rep_freq": "WEEKLY", "rep_dias": ["TH", "TU"], "rep_ate": "2026-12-12",
		"progresso_modo": "nenhum", "link_rotulo": ["Moodle", ""], "link_url": ["https://moodle.example", ""],
		"voltar": "/semana",
	}
	r = client.post("/itens/novo", data=form, follow_redirects=False)
	assert r.status_code == 303 and r.headers["location"] == "/semana"
	item = client.get("/api/itens").json()[0]
	assert item["recorrencia"] == "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261212T235959"
	assert item["inicio"] == "2026-10-20T19:00:00" and item["fim"] == "2026-10-20T22:00:00"
	assert [l["rotulo"] for l in item["links"]] == ["Moodle"]

	# o formulário de edição volta com os presets preenchidos
	html = client.get(f"/itens/{item['id']}").text
	assert "freq: 'WEEKLY'" in html and 'value="TU" checked' in html and 'value="2026-12-12"' in html

	# edição: tira a recorrência, vira dia inteiro e ganha prazo
	form.update(rep_freq="", hora_inicio="", hora_fim="", prazo_data="2026-10-25", voltar="/")
	r = client.post(f"/itens/{item['id']}", data=form, follow_redirects=False)
	assert r.status_code == 303
	item = client.get(f"/api/itens/{item['id']}").json()
	assert item["recorrencia"] is None and item["dia_inteiro"] is True and item["fim"] is None
	assert item["prazo"] == "2026-10-25T23:59:00"


def test_form_item_erros_reexibem_o_formulario(client, area_id):
	base = {"titulo": "X", "area_id": area_id, "progresso_modo": "nenhum"}
	r = client.post("/itens/novo", data={**base, "data": "2026-10-20", "hora_inicio": "20:00", "hora_fim": "19:00"})
	assert r.status_code == 200 and "fim não pode ser antes do início" in r.text and 'value="X"' in r.text
	r = client.post("/itens/novo", data={**base, "data": "2026-10-20", "rep_freq": "custom", "rep_custom": "FREQ=NUNCA"})
	assert "recorrência inválida" in r.text
	r = client.post("/itens/novo", data={"titulo": "Sem área", "progresso_modo": "nenhum"})
	assert "area_id é obrigatória" in r.text
	assert client.get("/api/itens").json() == []


def test_form_item_repetir_sem_dia_avisa(client, area_id):
	r = client.post("/itens/novo", data={"titulo": "Algum dia", "area_id": area_id, "rep_freq": "DAILY", "progresso_modo": "nenhum"})
	assert "escolha o dia de início" in r.text and client.get("/api/itens").json() == []


def test_form_projeto_e_item_herda(client, area_id):
	r = client.post("/projetos/novo", data={
		"nome": "Cliente X", "area_id": area_id, "prioridade": "critica", "status": "ativo",
		"progresso_modo": "quantidade", "progresso_atual": "4", "progresso_total": "8", "progresso_unidade": "h",
	}, follow_redirects=False)
	assert r.status_code == 303
	pid = int(r.headers["location"].rsplit("/", 1)[1])
	assert client.get(f"/api/projetos/{pid}").json()["progresso"] == 50.0
	client.post("/itens/novo", data={"titulo": "Entrega", "projeto_id": pid, "area_id": "", "prioridade": "", "progresso_modo": "nenhum"})
	item = client.get(f"/api/projetos/{pid}/itens").json()[0]
	assert item["prioridade"] == "critica" and item["area_id"] == area_id
	assert "Entrega" in client.get(f"/projetos/{pid}").text
	r = client.post(f"/projetos/{pid}/excluir", follow_redirects=False)
	assert r.status_code == 303 and client.get(f"/api/itens/{item['id']}").json()["projeto_id"] is None


def test_voltar_so_aceita_caminho_local(client, area_id):
	r = client.post("/itens/novo", data={"titulo": "A", "area_id": area_id, "progresso_modo": "nenhum", "voltar": "https://evil.example"}, follow_redirects=False)
	assert r.headers["location"] == "/"
	r = client.post("/itens/novo", data={"titulo": "B", "area_id": area_id, "progresso_modo": "nenhum", "voltar": "//evil.example"}, follow_redirects=False)
	assert r.headers["location"] == "/"


def test_areas_web(client):
	client.post("/areas", data={"nome": "Saúde", "cor": "#ff8800"})
	nomes = {a["nome"]: a for a in client.get("/api/areas").json()}
	assert nomes["Saúde"]["cor"] == "#ff8800"
	r = client.post("/areas", data={"nome": "Saúde", "cor": "#ff8800"})
	assert "já existe" in r.text
	client.post(f"/areas/{nomes['Saúde']['id']}/excluir")
	assert "Saúde" not in {a["nome"] for a in client.get("/api/areas").json()}


def test_semana_navega(client, area_id):
	client.post("/api/itens", json={"titulo": "Reunião", "area_id": area_id, "inicio": "2026-10-21T10:00:00"})
	html = client.get("/semana?inicio=2026-10-22").text  # qualquer dia cai na semana seg–dom
	assert "19/10 – 25/10" in html and "Reunião" in html
	assert "/semana?inicio=2026-10-12" in html and "/semana?inicio=2026-10-26" in html


def test_recorrencia_presets():
	assert recorrencia.montar_regra("WEEKDAYS") == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
	assert recorrencia.montar_regra("") is None
	assert recorrencia.ler_regra("FREQ=WEEKLY;INTERVAL=2")["freq"] == "custom"
	assert recorrencia.descrever("FREQ=WEEKLY;BYDAY=MO,WE,FR") == "toda seg, qua e sex"
	assert recorrencia.descrever("FREQ=DAILY;UNTIL=20261212T235959") == "todo dia até 12/12/2026"
	assert recorrencia.ler_regra(recorrencia.montar_regra("WEEKLY", ["FR", "MO"], date(2026, 12, 1)))["dias"] == ["MO", "FR"]
