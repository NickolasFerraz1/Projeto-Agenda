# Próximos passos

_Atualizado em 20/10/2026_

## Onde paramos
- **Fase 5 concluída** e rodando no Pi:
  - 5.1 backend · 5.2 interface PWA · 5.2.1 hierarquia · 5.2.2 importador de planos · 5.2.3 agendar etapa (remarcar, empurrar, agendar sozinho)
  - 5.3 deploy no Pi (serviço `agenda` na 8090, backup diário, Tailscale + `tailscale serve`)
  - 5.4 Google Agenda (só o Pi sincroniza; PC e notebook com `AGENDA_GCAL_ID` comentado)
  - 5.5 espelho lendo `/api/hoje` e `/api/agenda` (repo MagicMirror)
- App instalado como PWA no notebook e no celular (falta o PC): `https://magicmirror.tailc1dcbd.ts.net`.
- **6.1 Pular dia de recorrente** ✅ · **6.2 Visão de mês** ✅ · **6.3 Ordenar arrastando** ✅ · **6.3.1 Mover arrastando no Calendário** ✅ · **6.3.2 Tarefas em ordem** ✅ (ver abaixo).
- Aba **Semana** renomeada para **Calendário** (dentro: seletor Semana | Mês).
- App recarrega sozinho quando o servidor foi atualizado com a janela aberta (cabeçalho `X-Agenda-Versao` → `HX-Refresh`).

## Fase 6 — melhorias no app (em andamento)
| # | Item | Status |
|---|---|---|
| 6.1 | **Pular dia de recorrente** | ✅ botão ⏭ na linha da agenda (Hoje/Semana); pulado ≠ feito; no Google o dia some (EXDATE); no espelho fica tracejado e libera o horário |
| 6.2 | **Visão de mês** | ✅ seletor Semana \| Mês; grade seg–dom com até 3 itens por dia (+N), no celular pontinhos coloridos; tocar no dia abre o painel com ✓/⏭ e "+ Item" |
| 6.3 | **Ordenar arrastando** | ✅ alça ⠿ nas tarefas em aberto e nas etapas/subprojetos (mouse e toque); agendamento segue a nova ordem; reimportar o plano não desfaz |
| 6.3.1 | **Mover arrastando no Calendário** | ✅ Semana (PC e celular, segurar ~¼ s) e Mês (PC): soltar em outro dia move na hora (mesmo horário, aviso com "Desfazer"); no mesmo dia abre a janela "Mover" (sugere logo depois do item de cima); recorrente move só aquela ocorrência (Google: EXDATE + evento avulso) |
| 6.3.2 | **Tarefas em ordem (dependentes)** | ✅ opção no projeto (herdada pelas etapas; planos importados já vêm ligados): no calendário a tarefa não passa da anterior/seguinte. Reordenar no projeto refaz os horários marcados em qualquer projeto (livre ou em ordem) |
| 6.4 | **Botão no Obsidian**: endpoint com token + comando no Obsidian (Shell Commands/QuickAdd) → `/api/planos/importar` | próximo |
| 6.5 | **Plano com IA**: objetivo → plano no formato do importador → prévia → importar. Decidir modelo/custo; ideia de um modelo especializado em planos | — |

### 6.1 — como funciona
- Recorrente na agenda: ✓ = fiz · ⏭ = pulei (não fiz e não vou fazer). ⏭ de novo desfaz; ✓ num dia pulado vira feito.
- Rotas: `POST /pular/{id}?dia=AAAA-MM-DD` (web) e `PUT /api/itens/{id}/ocorrencias` com `status: "pulado"` (API).
- Google: dias pulados viram `EXDATE` no evento recorrente.

### 6.2 — como funciona
- `/mes?m=AAAA-MM&dia=AAAA-MM-DD` (dados do `/api/agenda`, 5 ou 6 semanas); painel do dia via `/mes/dia/AAAA-MM-DD` (HTMX).
- Ideia guardada: levar o mês para o espelho como terceiro modo do MMM-Agenda.

### 6.3 — como funciona
- SortableJS 1.15.6 em `app/static/vendor`; `POST /api/projetos/{id}/ordenar` `{tipo: itens|subprojetos, ids: [...]}` grava `ordem` 1..n.
- O projeto ganha `ordem_manual`: o importador mantém a ordem dos existentes e põe os novos no fim.
- Num plano sequencial, mudar a ordem das etapas muda qual etapa está liberada.

### 6.3.1 — como funciona
- `POST /mover/{id}` (form `data`, `hora` opcional, `orig` para recorrente). Item normal: muda início/fim mantendo a duração. Prazo sem horário não arrasta.
- Recorrente: `Ocorrencia` ganhou `inicio`/`fim` (horário só daquele dia) e o status `a_fazer`; "Voltar ao horário de sempre" na janela desfaz.
- `/api/agenda` devolve `ocorrencia_data` (dia original) e `movida`; ✓/⏭ usam o dia original.

### 6.3.2 — como funciona
- `Projeto.tarefas_em_ordem` (efetivo = ele ou algum ancestral). Migração liga nos planos sequenciais (raiz) que já existiam.
- Reordenar itens (qualquer projeto): `agendar.reorganizar` → `planejar(empurrar, so_itens=as já marcadas)` nos horários guardados, a partir da 1ª data; sem horários guardados só a ordem muda (aviso).
- `/mover`: recusa (422) se o novo início não fica entre a anterior e a seguinte (em aberto e com data).
- Projeto livre (desligado): calendário livre (a reorganização ao reordenar vale igual).
- Cuidado no `base.html`: o script do fim do body roda de novo a cada navegação do hx-boost — nada de `const`/`let` no nível de cima (redeclarar quebra tudo).

104 testes passando. `ASSET_VERSION` = 15.

## Ao retomar
1. Conferir se os zips 6.1, 6.2, 6.2.1 e 6.2.2 (app) e 6.1 (espelho) foram extraídos, commitados e atualizados no Pi.
2. Recarregar o app uma última vez em cada aparelho (depois disso a recarga é automática).
3. Instalar o PWA no PC.
4. Seguir com a **6.4 — botão no Obsidian**.

## Como retomar (desenvolvimento)
```powershell
cd <pasta do repo>
.venv\Scripts\activate
pytest -q
uvicorn app.main:app --reload --port 8090   # sem Google: AGENDA_GCAL_ID comentado no .env
```
No Pi (depois do push): `cd ~/projeto-agenda && git pull && bash scripts/instalar_pi.sh`.

## Lembretes
- Entregas em zip só com o que mudou (extrair na raiz e substituir; arquivos a apagar vêm avisados).
- **Só o Pi sincroniza com o Google** (senão PC e Pi brigam pela agenda "Espelho").
- Mudou CSS/JS/ícones → incrementar `ASSET_VERSION` em `app/config.py`.
- `.env` e `data/` (banco e `google-credenciais.json`) fora do Git; credenciais só por pendrive/scp.
- Notas longas ficam no Obsidian; no app, só anotações curtas.
- Mover os repos para fora do OneDrive (o OneDrive mexe na pasta `.git` e causa erros de lock).
- Planejamento completo da Fase 5: `docs/APP-TAREFAS.md`.
