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


def test_pular_dia_de_recorrente(client, area_id):
	from datetime import date, timedelta

	hoje = date.today()
	it = client.post("/api/itens", json={"titulo": "Piano", "area_id": area_id, "inicio": f"{hoje}T19:00:00",
		"recorrencia": "FREQ=DAILY"}).json()
	# pular: linha volta com estado "pulado" e o botão de desfazer
	r = client.post(f"/pular/{it['id']}?dia={hoje}")
	assert r.status_code == 200 and "pulado" in r.text and "Desfazer" in r.text
	dia = client.get(f"/api/agenda?de={hoje}&ate={hoje}").json()
	assert dia[0]["status"] == "pulado"
	# marcar como feito um dia pulado: vira concluído (não desmarca)
	client.post(f"/alternar/{it['id']}?tipo=agendado&dia={hoje}")
	assert client.get(f"/api/agenda?de={hoje}&ate={hoje}").json()[0]["status"] == "concluido"
	# pular de novo e desfazer: volta a "a fazer"
	client.post(f"/pular/{it['id']}?dia={hoje}")
	client.post(f"/pular/{it['id']}?dia={hoje}")
	assert client.get(f"/api/agenda?de={hoje}&ate={hoje}").json()[0]["status"] == "a_fazer"
	# só recorrentes, e só em dias em que o item acontece
	unico = client.post("/api/itens", json={"titulo": "X", "area_id": area_id, "inicio": f"{hoje}T10:00:00"}).json()
	assert client.post(f"/pular/{unico['id']}?dia={hoje}").status_code == 422
	assert client.post(f"/pular/{it['id']}?dia={hoje - timedelta(days=3)}").status_code == 422


def test_visao_de_mes(client, area_id):
	client.post("/api/itens", json={"titulo": "Consulta", "area_id": area_id, "inicio": "2026-02-10T09:00:00"})
	client.post("/api/itens", json={"titulo": "Entrega", "area_id": area_id, "prazo": "2026-02-27T23:59:00"})
	client.post("/api/itens", json={"titulo": "Piano", "area_id": area_id, "inicio": "2026-01-26T19:00:00",
		"recorrencia": "FREQ=WEEKLY;BYDAY=TU"})
	for n in range(4):  # 4 itens no mesmo dia: 3 aparecem + "+1"
		client.post("/api/itens", json={"titulo": f"T{n}", "area_id": area_id, "inicio": f"2026-02-12T1{n}:00:00"})
	html = client.get("/mes?m=2026-02").text
	# fevereiro/2026 começa num domingo: grade de seg 26/01 a dom 01/03 = 5 semanas
	assert html.count('class="mes-dia') == 35
	assert "Fevereiro 2026" in html and "Consulta" in html and "⏰" in html and "+1" in html
	assert html.count(">Piano<") == 5  # terças de 27/01 a 24/02 (a de 27/01 aparece apagada, fora do mês)
	# painel do dia (padrão: dia 1 quando o mês não é o atual) e via HTMX
	assert 'id="painel-dia"' in html
	painel = client.get("/mes/dia/2026-02-10").text
	assert "Consulta" in painel and "<html" not in painel
	assert "Nada marcado" in client.get("/mes/dia/2026-02-11").text
	# dia escolhido na URL, mês inválido cai no atual, seletor Semana | Mês nas duas telas
	assert "terça, 10 de fev" in client.get("/mes?m=2026-02&dia=2026-02-10").text
	assert client.get("/mes?m=xx").status_code == 200
	assert 'class="alternar-vista"' in client.get("/semana").text


def test_versao_antiga_recarrega_a_pagina(client):
	from app import config

	assert f'"X-Agenda-Versao": "{config.ASSET_VERSION}"' in client.get("/").text
	atual = {"HX-Request": "true", "HX-Boosted": "true", "X-Agenda-Versao": config.ASSET_VERSION}
	assert "HX-Refresh" not in client.get("/mes", headers=atual).headers
	antiga = {**atual, "X-Agenda-Versao": "1"}
	assert client.get("/mes", headers=antiga).headers["HX-Refresh"] == "true"
	assert "HX-Refresh" not in client.get("/mes", headers={"X-Agenda-Versao": "1"}).headers  # navegação normal


def test_mover_item_arrastando(client, area_id):
	it = client.post("/api/itens", json={"titulo": "Reunião", "area_id": area_id, "inicio": "2026-11-04T14:00:00",
		"fim": "2026-11-04T15:30:00"}).json()
	# outro dia, mesma hora: duração mantida
	assert client.post(f"/mover/{it['id']}", data={"data": "2026-11-06"}).status_code == 204
	novo = client.get(f"/api/itens/{it['id']}").json()
	assert (novo["inicio"], novo["fim"]) == ("2026-11-06T14:00:00", "2026-11-06T15:30:00")
	# outro horário
	client.post(f"/mover/{it['id']}", data={"data": "2026-11-06", "hora": "21:00"})
	novo = client.get(f"/api/itens/{it['id']}").json()
	assert (novo["inicio"], novo["fim"]) == ("2026-11-06T21:00:00", "2026-11-06T22:30:00")
	# dia inteiro: só a data; só prazo: não move; data inválida
	dt = client.post("/api/itens", json={"titulo": "Feriado", "area_id": area_id, "inicio": "2026-11-02T00:00:00", "dia_inteiro": True}).json()
	client.post(f"/mover/{dt['id']}", data={"data": "2026-11-03", "hora": "10:00"})
	assert client.get(f"/api/itens/{dt['id']}").json()["inicio"] == "2026-11-03T00:00:00"
	pz = client.post("/api/itens", json={"titulo": "Entrega", "area_id": area_id, "prazo": "2026-11-10T23:59:00"}).json()
	assert client.post(f"/mover/{pz['id']}", data={"data": "2026-11-11"}).status_code == 422
	assert client.post(f"/mover/{it['id']}", data={"data": "ontem"}).status_code == 422
	# a semana marca as linhas que podem ser arrastadas e traz a janela "Mover"
	html = client.get("/semana?inicio=2026-11-02").text
	assert 'data-arrastar-dia="2026-11-06"' in html and f'data-item="{it["id"]}"' in html and 'id="mover"' in html


def test_mover_so_uma_ocorrencia_de_recorrente(client, area_id):
	acad = client.post("/api/itens", json={"titulo": "Academia", "area_id": area_id, "inicio": "2026-11-02T14:00:00",
		"fim": "2026-11-02T15:00:00", "recorrencia": "FREQ=DAILY"}).json()
	aid = acad["id"]
	assert client.post(f"/mover/{aid}", data={"data": "2026-11-03", "hora": "21:00"}).status_code == 422  # falta orig
	assert client.post(f"/mover/{aid}", data={"data": "2026-11-03", "hora": "21:00", "orig": "2026-11-03"}).status_code == 204
	dia = lambda d: [(e["inicio"], e["status"], e["movida"]) for e in client.get(f"/api/agenda?de={d}&ate={d}").json()]  # noqa: E731
	assert dia("2026-11-03") == [("2026-11-03T21:00:00", "a_fazer", True)]
	assert dia("2026-11-04") == [("2026-11-04T14:00:00", "a_fazer", False)]  # as outras seguem a regra
	# para outro dia: some do original e aparece no novo (ao lado da do próprio dia)
	client.post(f"/mover/{aid}", data={"data": "2026-11-05", "hora": "07:00", "orig": "2026-11-03"})
	assert dia("2026-11-03") == []
	assert [x[0] for x in dia("2026-11-05")] == ["2026-11-05T07:00:00", "2026-11-05T14:00:00"]
	# feito/desfeito mantém o horário movido
	client.post(f"/alternar/{aid}?tipo=agendado&dia=2026-11-03")
	assert dia("2026-11-05")[0] == ("2026-11-05T07:00:00", "concluido", True)
	client.post(f"/alternar/{aid}?tipo=agendado&dia=2026-11-03")
	assert dia("2026-11-05")[0] == ("2026-11-05T07:00:00", "a_fazer", True)
	# voltar ao horário de sempre: sem hora, no dia original -> registro some
	client.post(f"/mover/{aid}", data={"data": "2026-11-03", "orig": "2026-11-03"})
	assert dia("2026-11-03") == [("2026-11-03T14:00:00", "a_fazer", False)]
	assert client.get(f"/api/itens/{aid}/ocorrencias").json() == []
