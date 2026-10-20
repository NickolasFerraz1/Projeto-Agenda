"""Importador de planejamento (Markdown do Obsidian -> projetos e itens)."""
import pytest

from app.services import plano

PIANO = """\
---
agenda: plano
projeto: Piano
area: lazer
sequencial: true
obsidian: obsidian://open?vault=Notas&file=Piano%2FPlanejamento
---
%% comentário
de várias linhas %%
# Objetivo
Tocar músicas simples em 10 semanas.

## Semana 1
Meta da semana: postura.
- [x] Postura e posição das mãos | 1h | [vídeo](https://youtu.be/a)
- [ ] Notas do teclado | 45min | [site](https://x.com/notas) [pdf](https://x.com/n.pdf)
    revisar com metrônomo
- [ ] Escala de Dó | 30min | 1 de 3 repetições | !alta

## Semana 2
- [ ] Acordes maiores | 1h30
### Extra
- [ ] Ritmo | 20min | algo desconhecido
"""


def test_ler_estrutura():
	p = plano.ler(PIANO)
	assert (p.raiz.nome, p.area, p.sequencial) == ("Piano", "lazer", True)
	assert p.raiz.notas == ["Tocar músicas simples em 10 semanas."]
	s1, s2 = p.raiz.etapas
	assert s1.notas == ["Meta da semana: postura."]
	postura, notas, escala = s1.tarefas
	assert postura.feito and postura.duracao_min == 60 and postura.links == [("vídeo", "https://youtu.be/a")]
	assert notas.links == [("site", "https://x.com/notas"), ("pdf", "https://x.com/n.pdf")] and notas.notas == ["revisar com metrônomo"]
	assert (escala.qtd_atual, escala.qtd_total, escala.qtd_unidade, escala.prioridade) == (1, 3, "repetições", "alta")
	assert [e.nome for e in s2.etapas] == ["Extra"] and s2.etapas[0].nivel == 3
	assert s2.etapas[0].tarefas[0].notas == ["algo desconhecido"]  # campo desconhecido vira nota


@pytest.mark.parametrize(
	"texto,erro",
	[("## Semana 1\n- [ ] X", "projeto"), ("---\nprojeto: X\n- [ ] a", "não fecha"), ("---\nprojeto: X\n---\n- [ ]  | 1h", "sem título")],
)
def test_ler_erros(texto, erro):
	with pytest.raises(plano.ErroPlano, match=erro):
		plano.ler(texto)


def test_modelo_e_prompts_saem_da_mesma_especificacao():
	p = plano.ler(plano.MODELO)  # o modelo é sempre um plano válido
	assert p.raiz.etapas and p.raiz.etapas[0].tarefas
	for modo in ("criar", "converter"):
		txt = plano.prompt(modo)
		assert plano.FORMATO in txt and plano.MODELO in txt
	assert "[o que quero aprender" in plano.prompt("criar")
	assert "[cole aqui o seu planejamento]" in plano.prompt("converter")


def test_previa_nao_grava(client):
	r = client.post("/api/planos/previa", json={"texto": PIANO})
	assert r.status_code == 200, r.text
	c = r.json()["contagem"]
	assert c == {"projeto_novo": 1, "etapa_novo": 3, "item_novo": 5}
	assert client.get("/api/projetos").json() == [] and client.get("/api/itens").json() == []


def test_importar_cria_hierarquia(client):
	r = client.post("/api/planos/importar", json={"texto": PIANO}).json()
	piano = client.get(f"/api/projetos/{r['projeto_id']}").json()
	assert piano["sequencial"] and piano["notas"] == "Tocar músicas simples em 10 semanas."
	assert [l["rotulo"] for l in piano["links"]] == ["Planejamento (Obsidian)"]
	etapas = client.get(f"/api/projetos?pai_id={piano['id']}").json()
	assert [(e["nome"], e["bloqueado"]) for e in etapas] == [("Semana 1", False), ("Semana 2", True)]
	itens = client.get(f"/api/projetos/{etapas[0]['id']}/itens").json()
	assert [i["titulo"] for i in itens] == ["Postura e posição das mãos", "Notas do teclado", "Escala de Dó"]  # ordem do plano
	postura, notas, escala = itens
	assert postura["status"] == "concluido" and notas["notas"] == "revisar com metrônomo" and len(notas["links"]) == 2
	assert escala["progresso_modo"] == "quantidade" and escala["progresso_total"] == 3 and escala["prioridade"] == "alta"
	assert escala["area_id"] == piano["area_id"]
	# pendências: só a etapa liberada aparece
	assert {i["titulo"] for i in client.get("/api/hoje").json()["pendencias"]} == {"Notas do teclado", "Escala de Dó"}


def test_reimportar_atualiza_sem_duplicar_e_preserva_o_app(client):
	pid = client.post("/api/planos/importar", json={"texto": PIANO}).json()["projeto_id"]
	s1 = client.get(f"/api/projetos?pai_id={pid}").json()[0]
	itens = {i["titulo"]: i for i in client.get(f"/api/projetos/{s1['id']}/itens").json()}
	# no app: conclui "Notas do teclado", avança a escala para 2/3 e cria um item extra
	client.patch(f"/api/itens/{itens['Notas do teclado']['id']}", json={"status": "concluido"})
	client.patch(f"/api/itens/{itens['Escala de Dó']['id']}", json={"progresso_atual": 2})
	client.post("/api/itens", json={"titulo": "Item criado no app", "projeto_id": s1["id"]})

	novo = PIANO.replace("Escala de Dó | 30min", "Escala de Dó | 40min").replace(
		"## Semana 2", "- [ ] Arpejos | 30min\n\n## Semana 2"
	) + "\n## Semana 3\n- [ ] Música simples | 1h\n"
	prev = client.post("/api/planos/previa", json={"texto": novo}).json()
	assert prev["contagem"]["item_novo"] == 2 and prev["contagem"]["etapa_novo"] == 1
	assert prev["contagem"]["item_atualizado"] == 1  # só a escala mudou
	assert any("Item criado no app" in m for m in prev["mantidos"])

	client.post("/api/planos/importar", json={"texto": novo})
	assert len(client.get("/api/projetos?raiz=true").json()) == 1
	itens = {i["titulo"]: i for i in client.get(f"/api/projetos/{s1['id']}/itens").json()}
	assert set(itens) == {"Postura e posição das mãos", "Notas do teclado", "Escala de Dó", "Arpejos", "Item criado no app"}
	assert itens["Notas do teclado"]["status"] == "concluido"  # o plano diz [ ], mas o app concluiu: mantém
	assert itens["Escala de Dó"]["progresso_atual"] == 2 and itens["Escala de Dó"]["duracao_min"] == 40
	assert len(client.get(f"/api/projetos?pai_id={pid}").json()) == 3


def test_importar_dentro_de_projeto_existente(client, area_id):
	pos = client.post("/api/projetos", json={"nome": "Pós FIAP", "area_id": area_id}).json()
	fase = client.post("/api/projetos", json={"nome": "Fase 3", "pai_id": pos["id"]}).json()
	txt = "---\nprojeto: Integração com CI/CD\ndentro: Pós FIAP › Fase 3\n---\n- [ ] Aula 1 | 0 de 5 vídeos\n"
	r = client.post("/api/planos/importar", json={"texto": txt}).json()
	bloco = client.get(f"/api/projetos/{r['projeto_id']}").json()
	assert bloco["pai_id"] == fase["id"] and bloco["area_id"] == area_id
	assert bloco["caminho"] == "Pós FIAP › Fase 3 › Integração com CI/CD"
	r = client.post("/api/planos/previa", json={"texto": txt.replace("Fase 3", "Fase 9")})
	assert r.status_code == 422 and "Fase 9" in r.json()["detail"]


def test_area_invalida(client):
	r = client.post("/api/planos/previa", json={"texto": "---\nprojeto: X\narea: Culinária\n---\n- [ ] a"})
	assert r.status_code == 422 and "Culinária" in r.json()["detail"]
	r = client.post("/api/planos/previa", json={"texto": "---\nprojeto: X\n---\n- [ ] a"})
	assert r.status_code == 422 and "area" in r.json()["detail"]


def test_tela_importar(client):
	html = client.get("/importar").text
	assert "Copiar prompt" in html and "Baixar .md" in html and plano.FORMATO.splitlines()[0] in html
	assert client.get("/importar/modelo.md").headers["content-disposition"].startswith("attachment")
	r = client.post("/importar/previa", data={"texto": PIANO})
	assert "Confirmar importação" in r.text and "Semana 2" in r.text
	r = client.post("/importar/previa", data={"texto": "sem cabeçalho"})
	assert 'class="erros"' in r.text
	r = client.post("/importar/aplicar", data={"texto": PIANO}, follow_redirects=False)
	assert r.status_code == 303 and r.headers["location"].startswith("/projetos/")
	assert client.get("/api/planos/prompt?modo=converter").text.startswith("Reescreva")


def test_ordem_arrastada_sobrevive_ao_reimportar(client):
	pid = client.post("/api/planos/importar", json={"texto": PIANO}).json()["projeto_id"]
	semanas = {p["nome"]: p["id"] for p in client.get(f"/api/projetos?pai_id={pid}").json()}
	s1 = semanas["Semana 1"]
	itens = {i["titulo"]: i["id"] for i in client.get(f"/api/projetos/{s1}/itens").json()}
	nova = [itens["Escala de Dó"], itens["Notas do teclado"], itens["Postura e posição das mãos"]]
	assert client.post(f"/api/projetos/{s1}/ordenar", json={"tipo": "itens", "ids": nova}).status_code == 200
	assert client.post(f"/api/projetos/{pid}/ordenar", json={"tipo": "subprojetos", "ids": [semanas["Semana 2"], s1]}).status_code == 200
	# reimportar (com uma tarefa nova) não desfaz a ordem; a nova vai para o fim
	client.post("/api/planos/importar", json={"texto": PIANO.replace("- [ ] Escala de Dó", "- [ ] Arpejo | 15min\n- [ ] Escala de Dó")})
	ordem = sorted(client.get(f"/api/projetos/{s1}/itens").json(), key=lambda i: i["ordem"])
	assert [i["titulo"] for i in ordem] == ["Escala de Dó", "Notas do teclado", "Postura e posição das mãos", "Arpejo"]
	subs = client.get(f"/api/projetos?pai_id={pid}").json()
	assert [p["nome"] for p in subs] == ["Semana 2", "Semana 1"]
	# página do projeto: alça só nos abertos e aviso de ordem manual
	html = client.get(f"/projetos/{s1}").text
	assert html.count('class="alca"') == 3 and 'data-ordenar="itens"' in html and "Ordem arrumada à mão" in html


def test_ordenar_valida_ids(client, area_id):
	a = client.post("/api/projetos", json={"nome": "A", "area_id": area_id}).json()
	b = client.post("/api/projetos", json={"nome": "B", "area_id": area_id}).json()
	ia = client.post("/api/itens", json={"titulo": "x", "area_id": area_id, "projeto_id": a["id"]}).json()
	ib = client.post("/api/itens", json={"titulo": "y", "area_id": area_id, "projeto_id": b["id"]}).json()
	assert client.post(f"/api/projetos/{a['id']}/ordenar", json={"tipo": "itens", "ids": [ia["id"], ib["id"]]}).status_code == 422
	assert client.post(f"/api/projetos/{a['id']}/ordenar", json={"tipo": "itens", "ids": [ia["id"], ia["id"]]}).status_code == 422
	assert client.post(f"/api/projetos/{a['id']}/ordenar", json={"tipo": "outro", "ids": [ia["id"]]}).status_code == 422
	assert client.post("/api/projetos/999/ordenar", json={"tipo": "itens", "ids": [1]}).status_code == 404
