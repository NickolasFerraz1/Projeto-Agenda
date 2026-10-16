"""Subprojetos, progresso em cascata, etapas sequenciais, duração, +1 e notas."""
import pytest

from app.routers.web import ler_duracao


def _proj(client, nome, area_id=None, **extra):
	dados = {"nome": nome, **extra}
	if area_id:
		dados["area_id"] = area_id
	r = client.post("/api/projetos", json=dados)
	assert r.status_code == 201, r.text
	return r.json()


def _item(client, titulo, projeto_id, **extra):
	r = client.post("/api/itens", json={"titulo": titulo, "projeto_id": projeto_id, **extra})
	assert r.status_code == 201, r.text
	return r.json()


def test_subprojeto_herda_e_tem_caminho(client, area_id):
	pos = _proj(client, "Pós FIAP", area_id, prioridade="alta")
	fase = _proj(client, "Fase 3", pai_id=pos["id"])
	bloco = _proj(client, "Integração com CI/CD", pai_id=fase["id"])
	assert bloco["area_id"] == area_id and bloco["prioridade"] == "alta"
	assert bloco["caminho"] == "Pós FIAP › Fase 3 › Integração com CI/CD"
	assert [p["nome"] for p in client.get("/api/projetos?raiz=true").json()] == ["Pós FIAP"]
	assert [p["nome"] for p in client.get(f"/api/projetos?pai_id={pos['id']}").json()] == ["Fase 3"]
	r = client.post("/api/projetos", json={"nome": "Órfão"})
	assert r.status_code == 422  # sem pai, a área é obrigatória


def test_nao_permite_ciclo(client, area_id):
	a = _proj(client, "A", area_id)
	b = _proj(client, "B", pai_id=a["id"])
	assert client.patch(f"/api/projetos/{a['id']}", json={"pai_id": b["id"]}).status_code == 422
	assert client.patch(f"/api/projetos/{a['id']}", json={"pai_id": a["id"]}).status_code == 422


def test_excluir_sobe_um_nivel(client, area_id):
	a = _proj(client, "A", area_id)
	b = _proj(client, "B", pai_id=a["id"])
	c = _proj(client, "C", pai_id=b["id"])
	i = _item(client, "Item de B", b["id"])
	client.delete(f"/api/projetos/{b['id']}")
	assert client.get(f"/api/projetos/{c['id']}").json()["pai_id"] == a["id"]
	assert client.get(f"/api/itens/{i['id']}").json()["projeto_id"] == a["id"]


def test_progresso_em_cascata_media_simples(client, area_id):
	pos = _proj(client, "Pós", area_id)
	bloco = _proj(client, "Bloco 1", pai_id=pos["id"])
	_item(client, "Aula 1", bloco["id"], progresso_modo="quantidade", progresso_atual=3, progresso_total=5)  # 60%
	feito = _item(client, "Aula 2", bloco["id"])
	client.patch(f"/api/itens/{feito['id']}", json={"status": "concluido"})  # 100%
	_item(client, "Hábito", bloco["id"], inicio="2026-10-01T07:00:00", recorrencia="FREQ=DAILY")  # não conta
	assert client.get(f"/api/projetos/{bloco['id']}").json()["progresso"] == 80.0
	vazio = _proj(client, "Bloco 2", pai_id=pos["id"])  # sem filhos: não entra na média
	assert client.get(f"/api/projetos/{pos['id']}").json()["progresso"] == 80.0
	client.patch(f"/api/projetos/{vazio['id']}", json={"status": "concluido"})  # concluído sem itens = 100%
	assert client.get(f"/api/projetos/{pos['id']}").json()["progresso"] == 90.0


def test_progresso_ponderado_pela_duracao(client, area_id):
	p = _proj(client, "Piano", area_id)
	a = _item(client, "Longo", p["id"], duracao_min=180)
	_item(client, "Curto", p["id"], duracao_min=60)
	client.patch(f"/api/itens/{a['id']}", json={"status": "concluido"})
	assert client.get(f"/api/projetos/{p['id']}").json()["progresso"] == 75.0  # 180 de 240 min
	_item(client, "Sem duração", p["id"])  # um filho sem peso -> média simples
	assert client.get(f"/api/projetos/{p['id']}").json()["progresso"] == round(100 / 3, 1)


def test_sequencial_trava_etapas_e_pendencias(client, area_id):
	piano = _proj(client, "Piano", area_id, sequencial=True)
	s1 = _proj(client, "Semana 1", pai_id=piano["id"])
	s2 = _proj(client, "Semana 2", pai_id=piano["id"])
	s10 = _proj(client, "Semana 10", pai_id=piano["id"])  # ordem natural: depois da 2
	t1 = _item(client, "Postura", s1["id"])
	_item(client, "Acordes", s2["id"])
	estado = {p["nome"]: p["bloqueado"] for p in client.get(f"/api/projetos?pai_id={piano['id']}").json()}
	assert list(estado) == ["Semana 1", "Semana 2", "Semana 10"]
	assert estado == {"Semana 1": False, "Semana 2": True, "Semana 10": True}
	assert [i["titulo"] for i in client.get("/api/hoje").json()["pendencias"]] == ["Postura"]

	client.patch(f"/api/itens/{t1['id']}", json={"status": "concluido"})  # Semana 1 = 100%
	estado = {p["nome"]: p["bloqueado"] for p in client.get(f"/api/projetos?pai_id={piano['id']}").json()}
	assert estado == {"Semana 1": False, "Semana 2": False, "Semana 10": True}
	assert [i["titulo"] for i in client.get("/api/hoje").json()["pendencias"]] == ["Acordes"]


def test_pendencias_ignoram_projeto_pausado(client, area_id):
	p = _proj(client, "Pausado", area_id)
	sub = _proj(client, "Sub", pai_id=p["id"])
	_item(client, "Dentro", sub["id"])
	assert len(client.get("/api/hoje").json()["pendencias"]) == 1
	client.patch(f"/api/projetos/{p['id']}", json={"status": "pausado"})
	assert client.get("/api/hoje").json()["pendencias"] == []


@pytest.mark.parametrize(
	"texto,minutos",
	[("1h", 60), ("1h30", 90), ("1h30min", 90), ("1:30", 90), ("90", 90), ("45min", 45), ("1,5h", 90), ("", None)],
)
def test_ler_duracao(texto, minutos):
	assert ler_duracao(texto) == minutos


def test_ler_duracao_invalida():
	with pytest.raises(ValueError):
		ler_duracao("uma hora")


def test_mais_um_conclui_ao_chegar_no_total(client, area_id):
	p = _proj(client, "Curso", area_id)
	i = _item(client, "Aula 1", p["id"], progresso_modo="quantidade", progresso_atual=3, progresso_total=5, progresso_unidade="vídeos")
	r = client.post(f"/incrementar/{i['id']}")
	assert "4/5 vídeos" in r.text and "+1" in r.text
	r = client.post(f"/incrementar/{i['id']}")
	item = client.get(f"/api/itens/{i['id']}").json()
	assert item["progresso_atual"] == 5 and item["status"] == "concluido" and "+1" not in r.text


def test_form_web_duracao_e_hierarquia(client, area_id):
	r = client.post("/projetos/novo", data={"nome": "Pós", "area_id": area_id, "progresso_modo": "itens"}, follow_redirects=False)
	pos = int(r.headers["location"].rsplit("/", 1)[1])
	r = client.post("/projetos/novo", data={"nome": "Fase 1", "pai_id": pos, "area_id": "", "prioridade": "", "sequencial": "on", "progresso_modo": "itens"}, follow_redirects=False)
	fase = int(r.headers["location"].rsplit("/", 1)[1])
	assert client.get(f"/api/projetos/{fase}").json()["sequencial"] is True
	client.post("/itens/novo", data={"titulo": "Aula 1", "projeto_id": fase, "duracao": "1h30", "progresso_modo": "nenhum"})
	item = client.get(f"/api/projetos/{fase}/itens").json()[0]
	assert item["duracao_min"] == 90
	html = client.get(f"/projetos/{pos}").text
	assert "Fase 1" in html and "Subprojetos" in html
	html = client.get(f"/projetos/{fase}").text
	assert 'href="/projetos/%d"' % pos in html and "1h30" in html  # trilha + duração
	assert "Pós › Fase 1" in client.get("/itens/novo").text  # projeto com caminho no formulário
	r = client.post("/itens/novo", data={"titulo": "X", "area_id": area_id, "duracao": "muito", "progresso_modo": "nenhum"})
	assert "duração inválida" in r.text


def test_markdown_seguro(client, area_id):
	r = client.post("/markdown", data={"notas": "**oi** <script>alert(1)</script> [x](javascript:alert(1)) [ok](https://a.b)"})
	assert "<strong>oi</strong>" in r.text and "<script>" not in r.text and 'href="javascript' not in r.text
	assert 'target="_blank"' in r.text
	p = _proj(client, "Com notas", area_id, notas="- item **forte**")
	assert "<li>item <strong>forte</strong></li>" in client.get(f"/projetos/{p['id']}").text
