# Próximos passos

_Atualizado em 16/10/2026_

## Onde paramos
- **5.1 Backend** ✅: FastAPI + SQLModel + SQLite; áreas, projetos, itens, links, ocorrências; progresso; recorrência (RRULE); `/api/agenda` e `/api/hoje`.
- **5.2 Interface (PWA)** ✅: Hoje (captura rápida, agenda, atrasados, pendências), Semana, Projetos, Item, Áreas; manifest, service worker, ícones.
- **5.2.1 Hierarquia** ✅ (zip entregue; conferir se foi extraído, testado e commitado):
  - subprojetos em níveis (Pós FIAP › Fase 3 › Bloco › aulas), trilha, herança de área/prioridade;
  - progresso automático em cascata (ponderado pela duração quando todos os filhos têm duração);
  - etapas sequenciais (🔒 travadas não aparecem nas pendências);
  - duração estimada, botão +1, notas em Markdown, "Repetir" sempre visível, prioridade baixa discreta;
  - migração automática de colunas (o `data/agenda.db` existente é atualizado sozinho).
- 53 testes passando.

## Como retomar
```powershell
cd C:\Users\nicko\Desktop\Projetos\Projeto-agenda
.venv\Scripts\activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload --port 8090
```
- App: http://localhost:8090 (celular: F12 → Ctrl+Shift+M)
- API: http://localhost:8090/docs
- Entregas chegam como **zip só com o que mudou**: extrair na raiz do repo e substituir. Se algum arquivo precisar ser apagado, vem avisado.

## 5.2.2 — Importador de planejamento ✅ (zip entregue; extrair, testar e commitar)
- Tela **Projetos → Importar plano** (`/importar`): copiar prompt (criar / converter), copiar ou baixar o modelo, enviar `.md` ou colar, **pré-visualizar** e confirmar.
- Formato: frontmatter (`projeto`, `area`, `dentro`, `sequencial`, `prioridade`, `obsidian`), `##`/`###` = etapas, `- [ ]` = tarefa com campos `| 1h | [rótulo](url) | 3 de 5 vídeos | !alta`; texto comum vira nota.
- Reimportar: atualiza pelo nome, não duplica, nunca apaga, preserva conclusões/progresso do app.
- API para o futuro botão do Obsidian: `POST /api/planos/previa` e `/api/planos/importar`.
- 64 testes passando.

## 5.2.3 — Agendar etapa ✅ (zip entregue; extrair, testar e commitar)
- Botão **Agendar** no projeto/etapa (`/projetos/{id}/agendar`): dias, hora de início, duração da sessão, "a partir de", remarcar atrasadas → **prévia por dia** → confirmar.
- Encaixa na ordem do plano, respeita a duração de cada tarefa (sem duração = 30 min), desvia do que já está na agenda; tarefa maior que a sessão ocupa a sessão e passa do horário.
- Num plano sequencial, só a etapa liberada entra. Horários guardados no plano: as próximas etapas herdam.
- Quando uma etapa libera e ainda está sem data: aviso na **Hoje** e no projeto com botão "Agendar".
- **Desagendar**: tarefas em aberto de hoje em diante voltam para "sem data".
- **Atrasadas** (2 modos): *remarcar nos espaços livres* (tarefas independentes: só a atrasada muda) ou *remarcar e empurrar as seguintes* (dependentes: redistribui a etapa mantendo a ordem).
- Na **Hoje**, cada tarefa atrasada de um projeto tem o botão 📅 → "Só esta" / "Esta e as seguintes", usando os horários guardados do plano.
- **Agendar sozinho** (planos sequenciais): ao concluir a última tarefa de uma etapa, a próxima é agendada nos horários do plano e aparece um aviso. Liga na tela Agendar ("Agendar as próximas etapas sozinho") ou em Editar projeto. Desligado: só o aviso com botão "Agendar".
- Prévia da importação: ✓ só nas concluídas, ○ nas abertas e duração por tarefa/etapa.
- 82 testes passando.

## Depois
1. **5.3 Deploy no Pi** ✅ (16/10; app em https://magicmirror.<tailnet>.ts.net, PWA instalado no celular, PC e notebook): `bash scripts/instalar_pi.sh` (venv, serviço `agenda` na porta 8090 só localhost, backup diário 03:30 mantendo 14), Tailscale no Pi/celular/PC, `sudo tailscale serve --bg 8090` (HTTPS → PWA instalável no celular).
2. **5.4 Google Agenda** (código pronto; falta configurar a conta de serviço e a agenda "Espelho" — README, seção Google Agenda): reconciliação app → Google após cada alteração e a cada 15 min; status em Áreas.
3. **5.5 Espelho**: coluna "Hoje" na Início e página Agenda lendo `/api/hoje` e `/api/agenda` (feito no repo do MagicMirror).

## Ideias para depois (combinadas, não esquecer)
- **Botão no Obsidian** ("Enviar para a Agenda"): plugin pequeno que manda a nota direto para a API do Pi via Tailscale.
- **Geração do plano com IA**: descrever o objetivo e receber o planejamento já no formato do importador (etapas, durações, fontes); idealmente um modelo/assistente especializado em montar planejamentos ótimos para qualquer objetivo.
- Marcar ocorrência de recorrente como "pulado"; visão de mês; ordem manual (arrastar).

## Lembretes
- Notas longas e conteúdo de estudo ficam no **Obsidian**; no app, só anotações curtas da tarefa (link para a nota do Obsidian quando precisar).
- Mudou CSS/JS/ícones → incrementar `ASSET_VERSION` em `app/config.py` (renova o cache do PWA).
- Banco `data/agenda.db` fora do Git. Colunas novas entram sozinhas; renomear/remover coluna exige migração manual.
- Planejamento completo da Fase 5: `docs/APP-TAREFAS.md`.
