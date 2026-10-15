def test_progresso_manual(client, area_id):
	i = client.post(
		"/api/itens",
		json={"titulo": "Implementação X", "area_id": area_id, "progresso_modo": "manual", "progresso_manual": 50},
	).json()
	assert i["progresso"] == 50


def test_progresso_por_quantidade(client, area_id):
	p = client.post(
		"/api/projetos",
		json={
			"nome": "Linux — Alura",
			"area_id": area_id,
			"progresso_modo": "quantidade",
			"progresso_atual": 4,
			"progresso_total": 8,
			"progresso_unidade": "h",
		},
	).json()
	assert p["progresso"] == 50.0
	p = client.patch(f"/api/projetos/{p['id']}", json={"progresso_atual": 10}).json()
	assert p["progresso"] == 100.0  # limitado a 100%


def test_progresso_por_itens(client, area_id):
	p = client.post("/api/projetos", json={"nome": "Matéria", "area_id": area_id, "progresso_modo": "itens"}).json()
	ids = [client.post("/api/itens", json={"titulo": f"Aula {n}", "projeto_id": p["id"]}).json()["id"] for n in range(4)]
	client.patch(f"/api/itens/{ids[0]}", json={"status": "concluido"})
	client.patch(f"/api/itens/{ids[1]}", json={"status": "cancelado"})  # não conta
	assert client.get(f"/api/projetos/{p['id']}").json()["progresso"] == round(100 / 3, 1)


def test_progresso_manual_fora_da_faixa(client, area_id):
	r = client.post("/api/itens", json={"titulo": "X", "area_id": area_id, "progresso_modo": "manual", "progresso_manual": 140})
	assert r.status_code == 422
