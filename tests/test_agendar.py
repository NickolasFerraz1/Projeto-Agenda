"""Agendar etapa: encaixe das tarefas nos horários de estudo."""
from datetime import date, datetime, time, timedelta

from sqlmodel import Session

from app import db
from app.services import agendar

# Segunda-feira, 19/10/2026, 10:00 (antes da sessão das 19h)
AGORA = datetime(2026, 10, 19, 10, 0)
SEG_QUA_SEX = agendar.Horarios(["MO", "WE", "FR"], time(19, 0), 60)


def _plano(client, area_id):
	piano = client.post("/api/projetos", json={"nome": "Piano", "area_id": area_id, "sequencial": True}).json()
	s1 = client.post("/api/projetos", json={"nome": "Semana 1", "pai_id": piano["id"]}).json()
	s2 = client.post("/api/projetos", json={"nome": "Semana 2", "pai_id": piano["id"]}).json()
	ids = {}
	for n, (titulo, dur) in enumerate([("Notas", 45), ("Cinco dedos", 30), ("Revisão", 15), ("Ritmo", 40)], start=1):
		ids[titulo] = client.post("/api/itens", json={"titulo": titulo, "projeto_id": s1["id"], "duracao_min": dur, "ordem": n}).json()["id"]
	client.post("/api/itens", json={"titulo": "Acordes", "projeto_id": s2["id"], "duracao_min": 60})
	return piano, s1, s2, ids


def _planejar(projeto_id, **kw):
	with Session(db.engine) as s:
		ag = agendar.planejar(s, projeto_id, kw.pop("h", SEG_QUA_SEX), agora=AGORA, **kw)
		return [(e.item.titulo, e.inicio, e.fim, e.estourou) for e in ag.encaixes], [i.titulo for i in ag.sobras], ag.avisos


def test_encaixa_na_ordem_respeitando_a_sessao(client, area_id):
	_, s1, _, _ = _plano(client, area_id)
	encaixes, sobras, _ = _planejar(s1["id"])
	assert [(t, i.strftime("%a %H:%M"), f.strftime("%H:%M")) for t, i, f, _ in encaixes] == [
		("Notas", "Mon 19:00", "19:45"),
		("Cinco dedos", "Wed 19:00", "19:30"),  # 45 + 30 > 60: vai para quarta
		("Revisão", "Wed 19:30", "19:45"),
		("Ritmo", "Fri 19:00", "19:40"),
	]
	assert sobras == []


def test_pula_sessao_que_ja_passou_e_respeita_a_partir(client, area_id):
	_, s1, _, _ = _plano(client, area_id)
	with Session(db.engine) as s:
		tarde = AGORA.replace(hour=21)  # segunda 21h: a sessão de hoje já acabou
		ag = agendar.planejar(s, s1["id"], SEG_QUA_SEX, agora=tarde)
		assert ag.encaixes[0].inicio == datetime(2026, 10, 21, 19, 0)  # quarta
		ag = agendar.planejar(s, s1["id"], SEG_QUA_SEX, a_partir=date(2026, 10, 23), agora=AGORA)
		assert ag.encaixes[0].inicio == datetime(2026, 10, 23, 19, 0)  # sexta


def test_desvia_do_que_ja_esta_na_agenda(client, area_id):
	_, s1, _, _ = _plano(client, area_id)
	client.post("/api/itens", json={"titulo": "Reunião", "area_id": area_id, "inicio": "2026-10-19T19:00:00", "fim": "2026-10-19T19:30:00"})
	encaixes, _, _ = _planejar(s1["id"])
	# Segunda: só sobram 30 min depois da reunião -> "Notas" (45) não cabe; "Cinco dedos" também não
	# entra antes dela porque a ordem do plano é mantida.
	assert encaixes[0][0] == "Notas" and encaixes[0][1] == datetime(2026, 10, 21, 19, 0)


def test_tarefa_maior_que_a_sessao(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Longo", "area_id": area_id}).json()
	client.post("/api/itens", json={"titulo": "Maratona", "projeto_id": p["id"], "duracao_min": 90})
	encaixes, _, _ = _planejar(p["id"])
	titulo, ini, fim, estourou = encaixes[0]
	assert estourou and (fim - ini) == timedelta(minutes=90)


def test_sem_duracao_usa_padrao_e_avisa(client, area_id):
	p = client.post("/api/projetos", json={"nome": "X", "area_id": area_id}).json()
	client.post("/api/itens", json={"titulo": "Sem duração", "projeto_id": p["id"]})
	encaixes, _, avisos = _planejar(p["id"])
	assert encaixes[0][2] - encaixes[0][1] == timedelta(minutes=agendar.DURACAO_PADRAO)
	assert any("sem duração" in a for a in avisos)


def test_remarcar_atrasadas(client, area_id):
	p = client.post("/api/projetos", json={"nome": "X", "area_id": area_id}).json()
	client.post("/api/itens", json={"titulo": "Atrasada", "projeto_id": p["id"], "duracao_min": 30, "inicio": "2026-10-16T19:00:00"})
	client.post("/api/itens", json={"titulo": "Futura", "projeto_id": p["id"], "duracao_min": 30, "inicio": "2026-10-30T19:00:00"})
	assert [e[0] for e in _planejar(p["id"])[0]] == ["Atrasada"]  # a futura não mexe
	assert _planejar(p["id"], remarcar=False)[0] == []


def test_api_simular_aplicar_guardar_horarios_e_desagendar(client, area_id):
	piano, s1, s2, ids = _plano(client, area_id)
	corpo = {"dias": ["MO", "WE", "FR"], "hora": "19:00", "minutos": 60, "a_partir": "2030-01-07", "simular": True}
	r = client.post(f"/api/projetos/{s1['id']}/agendar", json=corpo).json()
	assert len(r["encaixes"]) == 4 and not r["aplicado"]
	assert client.get(f"/api/itens/{ids['Notas']}").json()["inicio"] is None  # simulação não grava

	r = client.post(f"/api/projetos/{s1['id']}/agendar", json={**corpo, "simular": False}).json()
	assert r["aplicado"] and client.get(f"/api/itens/{ids['Notas']}").json()["inicio"] == "2030-01-07T19:00:00"
	plano = client.get(f"/api/projetos/{piano['id']}").json()  # horários guardados no plano (pai)
	assert (plano["agenda_dias"], plano["agenda_hora"], plano["agenda_minutos"]) == ("MO,WE,FR", "19:00", 60)
	assert "seg, qua, sex às 19:00" in client.get(f"/projetos/{s2['id']}/agendar").text  # etapa herda

	assert client.post(f"/api/projetos/{s1['id']}/desagendar").json()["removidos"] == 4
	assert client.get(f"/api/itens/{ids['Notas']}").json()["inicio"] is None
	assert client.post(f"/api/projetos/{s1['id']}/agendar", json={**corpo, "dias": ["XX"]}).status_code == 422


def test_sugestao_quando_etapa_libera(client, area_id):
	piano, s1, s2, ids = _plano(client, area_id)
	client.patch(f"/api/projetos/{piano['id']}", json={"agenda_dias": "MO,WE,FR", "agenda_hora": "19:00", "agenda_minutos": 60})
	assert "Semana 1</strong> está liberada" in client.get(f"/projetos/{piano['id']}").text
	assert "Semana 1 liberada e ainda sem data" in client.get("/").text
	for i in ids.values():
		client.patch(f"/api/itens/{i}", json={"status": "concluido"})
	assert "Semana 2</strong> está liberada" in client.get(f"/projetos/{piano['id']}").text


def test_tela_agendar(client, area_id):
	_, s1, _, _ = _plano(client, area_id)
	html = client.get(f"/projetos/{s1['id']}/agendar").text
	assert "Horários de estudo" in html and 'value="19:00"' in html
	dados = {"dias": ["MO", "WE"], "hora": "07:00", "minutos": "60", "a_partir": "2030-01-07", "atrasadas": "livres"}
	r = client.post(f"/projetos/{s1['id']}/agendar/previa", data=dados)
	assert "Confirmar agendamento" in r.text and "Notas" in r.text
	assert 'class="erros"' in client.post(f"/projetos/{s1['id']}/agendar/previa", data={**dados, "dias": []}).text
	r = client.post(f"/projetos/{s1['id']}/agendar", data=dados, follow_redirects=False)
	assert r.status_code == 303
	itens = client.get(f"/api/projetos/{s1['id']}/itens").json()
	assert all(i["inicio"] for i in itens)


def test_plano_sequencial_agenda_so_a_etapa_liberada(client, area_id):
	piano, s1, s2, ids = _plano(client, area_id)
	titulos = [e[0] for e in _planejar(piano["id"])[0]]
	assert "Acordes" not in titulos and titulos[0] == "Notas"  # Semana 2 está travada


def _etapa_agendada(client, area_id):
	"""Etapa com 3 tarefas de 30 min já agendadas: seg (atrasada em relação a AGORA2), qua, sex."""
	p = client.post("/api/projetos", json={"nome": "Curso", "area_id": area_id,
		"agenda_dias": "MO,WE,FR", "agenda_hora": "19:00", "agenda_minutos": 30}).json()
	ids = []
	for n, dia in enumerate(["2026-10-19", "2026-10-21", "2026-10-23"], start=1):
		ids.append(client.post("/api/itens", json={"titulo": f"Aula {n}", "projeto_id": p["id"], "duracao_min": 30, "ordem": n,
			"inicio": f"{dia}T19:00:00", "fim": f"{dia}T19:30:00"}).json()["id"])
	return p, ids


AGORA2 = datetime(2026, 10, 20, 10, 0)  # terça: a Aula 1 (segunda) ficou para trás


def test_remarcar_nos_espacos_livres_x_empurrar(client, area_id):
	p, ids = _etapa_agendada(client, area_id)
	with Session(db.engine) as s:
		h = agendar.Horarios.de_projeto(s.get(agendar.Projeto, p["id"]))
		livres = agendar.planejar(s, p["id"], h, agora=AGORA2)
		# só a Aula 1 muda; quarta e sexta estão ocupadas pelas aulas 2 e 3 -> vai para a segunda seguinte
		assert [(e.item.titulo, e.inicio.date().isoformat()) for e in livres.encaixes] == [("Aula 1", "2026-10-26")]
		emp = agendar.planejar(s, p["id"], h, agora=AGORA2, empurrar=True)
		assert [(e.item.titulo, e.inicio.date().isoformat()) for e in emp.encaixes] == [
			("Aula 1", "2026-10-21"), ("Aula 2", "2026-10-23"), ("Aula 3", "2026-10-26")]


def test_remarcar_pela_tela_hoje(client, area_id, monkeypatch):
	p, ids = _etapa_agendada(client, area_id)
	# "agora" fixo na terça para o serviço
	real = agendar.planejar
	monkeypatch.setattr(agendar, "planejar", lambda *a, **k: real(*a, **{**k, "agora": AGORA2}))
	r = client.post(f"/remarcar/{ids[0]}?modo=empurrar")
	assert "“Aula 1” remarcada" in r.text and "+2 seguintes empurradas" in r.text
	assert client.get(f"/api/itens/{ids[2]}").json()["inicio"] == "2026-10-26T19:00:00"
	# "só esta": volta a Aula 1 para segunda (atrasada); só ela anda, as outras ficam
	client.patch(f"/api/itens/{ids[0]}", json={"inicio": "2026-10-19T19:00:00", "fim": "2026-10-19T19:30:00"})
	antes = [client.get(f"/api/itens/{i}").json()["inicio"] for i in ids[1:]]
	r = client.post(f"/remarcar/{ids[0]}?modo=so")
	assert "“Aula 1” remarcada" in r.text and "empurrada" not in r.text
	assert [client.get(f"/api/itens/{i}").json()["inicio"] for i in ids[1:]] == antes


def test_remarcar_sem_horarios_redireciona(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Sem horário", "area_id": area_id}).json()
	i = client.post("/api/itens", json={"titulo": "X", "projeto_id": p["id"], "inicio": "2020-01-01T10:00:00"}).json()
	r = client.post(f"/remarcar/{i['id']}")
	assert r.headers["hx-redirect"] == f"/projetos/{p['id']}/agendar"


def test_hoje_mostra_menu_remarcar_nos_atrasados(client, area_id):
	p, ids = _etapa_agendada(client, area_id)
	client.patch(f"/api/itens/{ids[0]}", json={"inicio": "2020-01-06T19:00:00", "fim": "2020-01-06T19:30:00"})
	html = client.get("/").text
	assert f'/remarcar/{ids[0]}?modo=empurrar' in html and "Esta e as seguintes" in html


def _plano_auto(client, area_id, auto=True):
	piano, s1, s2, ids = _plano(client, area_id)
	client.patch(f"/api/projetos/{piano['id']}", json={"agenda_dias": "MO,WE,FR", "agenda_hora": "19:00", "agenda_minutos": 60, "agenda_auto": auto})
	return piano, s1, s2, ids


def test_auto_agenda_proxima_etapa_ao_concluir(client, area_id):
	piano, s1, s2, ids = _plano_auto(client, area_id)
	for titulo in ("Notas", "Cinco dedos", "Revisão"):
		client.patch(f"/api/itens/{ids[titulo]}", json={"status": "concluido"})
	acordes = client.get(f"/api/projetos/{s2['id']}/itens").json()[0]
	assert acordes["inicio"] is None  # Semana 1 ainda não terminou
	client.patch(f"/api/itens/{ids['Ritmo']}", json={"status": "concluido"})  # completa a Semana 1
	acordes = client.get(f"/api/projetos/{s2['id']}/itens").json()[0]
	assert acordes["inicio"] is not None and acordes["inicio"].endswith("19:00:00")
	# o aviso aparece uma vez na próxima página
	html = client.get("/").text
	assert "Semana 2 agendada sozinha" in html
	assert "Semana 2 agendada sozinha" not in client.get("/").text


def test_sem_auto_so_sugere(client, area_id):
	piano, s1, s2, ids = _plano_auto(client, area_id, auto=False)
	for i in ids.values():
		client.patch(f"/api/itens/{i}", json={"status": "concluido"})
	assert client.get(f"/api/projetos/{s2['id']}/itens").json()[0]["inicio"] is None
	assert "Semana 2 liberada e ainda sem data" in client.get("/").text


def test_auto_pelo_circulo_manda_toast_no_htmx(client, area_id):
	piano, s1, s2, ids = _plano_auto(client, area_id)
	for titulo in ("Notas", "Cinco dedos", "Revisão"):
		client.patch(f"/api/itens/{ids[titulo]}", json={"status": "concluido"})
	r = client.post(f"/alternar/{ids['Ritmo']}")
	assert "Semana 2 agendada sozinha" in r.headers.get("hx-trigger", "").encode().decode("unicode_escape")


def test_auto_ligado_pela_tela_agendar(client, area_id):
	piano, s1, s2, ids = _plano(client, area_id)
	html = client.get(f"/projetos/{s1['id']}/agendar").text
	assert "Agendar as próximas etapas sozinho" in html
	dados = {"dias": ["MO"], "hora": "19:00", "minutos": "60", "a_partir": "2030-01-07", "atrasadas": "livres", "auto": "on"}
	client.post(f"/projetos/{s1['id']}/agendar", data=dados)
	assert client.get(f"/api/projetos/{piano['id']}").json()["agenda_auto"] is True
	client.post(f"/projetos/{s1['id']}/agendar", data={k: v for k, v in dados.items() if k != "auto"})
	assert client.get(f"/api/projetos/{piano['id']}").json()["agenda_auto"] is False


def test_salvar_opcao_sem_tarefas_para_agendar(client, area_id):
	piano, s1, s2, ids = _plano(client, area_id)
	dados = {"dias": ["MO"], "hora": "19:00", "minutos": "60", "a_partir": "2030-01-07", "atrasadas": "livres"}
	client.post(f"/projetos/{s1['id']}/agendar", data=dados)  # agenda tudo
	r = client.post(f"/projetos/{s1['id']}/agendar/previa", data={**dados, "auto": "on"})
	assert "Salvar só os horários" in r.text and "Confirmar agendamento" not in r.text
	client.post(f"/projetos/{s1['id']}/agendar", data={**dados, "auto": "on"})
	assert client.get(f"/api/projetos/{piano['id']}").json()["agenda_auto"] is True


def test_agendar_segue_a_ordem_arrastada(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Curso", "area_id": area_id}).json()
	ids = [client.post("/api/itens", json={"titulo": t, "area_id": area_id, "projeto_id": p["id"], "duracao_min": 30}).json()["id"]
		for t in ("Aula 1", "Aula 2", "Aula 3")]
	client.post(f"/api/projetos/{p['id']}/ordenar", json={"tipo": "itens", "ids": [ids[2], ids[0], ids[1]]})
	r = client.post(f"/api/projetos/{p['id']}/agendar", json={"dias": ["MO"], "hora": "19:00", "minutos": 120,
		"a_partir": "2026-11-02", "simular": True}).json()
	assert [e["titulo"] for e in r["encaixes"]] == ["Aula 3", "Aula 1", "Aula 2"]


def _plano_em_ordem(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Piano", "area_id": area_id, "tarefas_em_ordem": True}).json()
	ids = {t: client.post("/api/itens", json={"titulo": t, "area_id": area_id, "projeto_id": p["id"], "duracao_min": 30}).json()["id"]
		for t in ("Aula 1", "Aula 2", "Aula 3")}
	r = client.post(f"/api/projetos/{p['id']}/agendar", json={"dias": ["MO", "WE"], "hora": "19:00", "minutos": 30,
		"a_partir": "2026-11-02"})
	assert r.status_code == 200
	return p, ids


def test_reordenar_tarefas_em_ordem_refaz_os_horarios(client, area_id):
	p, ids = _plano_em_ordem(client, area_id)
	ini = lambda t: client.get(f"/api/itens/{ids[t]}").json()["inicio"]  # noqa: E731
	assert [ini("Aula 1"), ini("Aula 2"), ini("Aula 3")] == ["2026-11-02T19:00:00", "2026-11-04T19:00:00", "2026-11-09T19:00:00"]
	r = client.post(f"/api/projetos/{p['id']}/ordenar", json={"tipo": "itens", "ids": [ids["Aula 3"], ids["Aula 1"], ids["Aula 2"]]})
	assert r.json() == {"reorganizadas": 3}
	assert [ini("Aula 3"), ini("Aula 1"), ini("Aula 2")] == ["2026-11-02T19:00:00", "2026-11-04T19:00:00", "2026-11-09T19:00:00"]
	assert "Horários reorganizados" in client.get("/").text  # aviso na próxima página


def test_calendario_nao_passa_da_vizinha(client, area_id):
	p, ids = _plano_em_ordem(client, area_id)
	# Aula 2 (qua 04/11): pode ir para ter 03/11 (entre a 1 e a 3)...
	assert client.post(f"/mover/{ids['Aula 2']}", data={"data": "2026-11-03"}).status_code == 204
	# ...mas não para antes da Aula 1 nem para depois da Aula 3
	r = client.post(f"/mover/{ids['Aula 2']}", data={"data": "2026-11-02", "hora": "08:00"})
	assert r.status_code == 422 and "Aula 1" in r.json()["detail"]
	r = client.post(f"/mover/{ids['Aula 2']}", data={"data": "2026-11-10"})
	assert r.status_code == 422 and "Aula 3" in r.json()["detail"]
	# projeto livre: no calendário move para qualquer lugar
	client.patch(f"/api/projetos/{p['id']}", json={"tarefas_em_ordem": False})
	assert client.post(f"/mover/{ids['Aula 2']}", data={"data": "2026-11-10"}).status_code == 204


def test_plano_importado_vem_em_ordem_e_herda_nas_etapas(client):
	txt = "---\nprojeto: Violão\narea: lazer\n---\n## Semana 1\n- [ ] A\n- [ ] B\n"
	pid = client.post("/api/planos/importar", json={"texto": txt}).json()["projeto_id"]
	assert client.get(f"/api/projetos/{pid}").json()["tarefas_em_ordem"] is True
	s1 = client.get(f"/api/projetos?pai_id={pid}").json()[0]["id"]
	assert "tarefas em ordem" in client.get(f"/projetos/{s1}").text


def test_reordenar_projeto_livre_tambem_refaz_os_horarios(client, area_id):
	p, ids = _plano_em_ordem(client, area_id)
	client.patch(f"/api/projetos/{p['id']}", json={"tarefas_em_ordem": False})
	r = client.post(f"/api/projetos/{p['id']}/ordenar", json={"tipo": "itens", "ids": [ids["Aula 2"], ids["Aula 1"], ids["Aula 3"]]})
	assert r.json() == {"reorganizadas": 3}
	assert client.get(f"/api/itens/{ids['Aula 2']}").json()["inicio"] == "2026-11-02T19:00:00"
