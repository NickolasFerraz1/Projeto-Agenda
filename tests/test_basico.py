def test_areas_padrao(client):
	nomes = {a["nome"] for a in client.get("/api/areas").json()}
	assert nomes == {"Estudo", "Trabalho", "Pessoal", "Lazer"}


def test_area_em_uso_nao_pode_ser_excluida(client, area_id):
	client.post("/api/projetos", json={"nome": "Curso", "area_id": area_id})
	assert client.delete(f"/api/areas/{area_id}").status_code == 409


def test_item_herda_area_e_prioridade_do_projeto(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Cliente X", "area_id": area_id, "prioridade": "critica"}).json()
	i = client.post("/api/itens", json={"titulo": "Implementar login", "projeto_id": p["id"]}).json()
	assert i["area_id"] == area_id
	assert i["prioridade"] == "critica"


def test_item_sem_projeto_exige_area(client):
	r = client.post("/api/itens", json={"titulo": "Solto"})
	assert r.status_code == 422


def test_links_e_substituicao(client, area_id):
	i = client.post(
		"/api/itens",
		json={"titulo": "Aula 3", "area_id": area_id, "links": [{"rotulo": "Aula", "url": "https://x/aula3"}]},
	).json()
	assert [l["rotulo"] for l in i["links"]] == ["Aula"]
	i = client.patch(f"/api/itens/{i['id']}", json={"links": [{"rotulo": "A", "url": "u1"}, {"rotulo": "B", "url": "u2"}]}).json()
	assert [l["rotulo"] for l in i["links"]] == ["A", "B"]


def test_fim_antes_do_inicio(client, area_id):
	r = client.post(
		"/api/itens",
		json={"titulo": "X", "area_id": area_id, "inicio": "2026-10-20T10:00", "fim": "2026-10-20T09:00"},
	)
	assert r.status_code == 422


def test_excluir_projeto_mantem_itens(client, area_id):
	p = client.post("/api/projetos", json={"nome": "P", "area_id": area_id}).json()
	i = client.post("/api/itens", json={"titulo": "I", "projeto_id": p["id"]}).json()
	assert client.delete(f"/api/projetos/{p['id']}").status_code == 204
	assert client.get(f"/api/itens/{i['id']}").json()["projeto_id"] is None


def test_horario_com_fuso_e_rejeitado(client, area_id):
	r = client.post("/api/itens", json={"titulo": "X", "area_id": area_id, "inicio": "2026-10-20T10:00:00Z"})
	assert r.status_code == 422
