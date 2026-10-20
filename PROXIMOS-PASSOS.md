# Próximos passos

_Atualizado em 20/10/2026_

## Onde paramos
- **Fase 5 concluída** e rodando no Pi:
  - 5.1 backend · 5.2 interface PWA · 5.2.1 hierarquia · 5.2.2 importador de planos · 5.2.3 agendar etapa (remarcar, empurrar, agendar sozinho)
  - 5.3 deploy no Pi (serviço `agenda` na 8090, backup diário, Tailscale + `tailscale serve`)
  - 5.4 Google Agenda (só o Pi sincroniza; PC e notebook com `AGENDA_GCAL_ID` comentado)
  - 5.5 espelho lendo `/api/hoje` e `/api/agenda` (repo MagicMirror)
- App instalado como PWA no notebook e no celular (falta o PC): `https://magicmirror.tailc1dcbd.ts.net`.
- **6.1 Pular dia de recorrente** ✅ (ver abaixo).

## Fase 6 — melhorias no app (em andamento)
| # | Item | Status |
|---|---|---|
| 6.1 | **Pular dia de recorrente** | ✅ botão ⏭ na linha da agenda (Hoje/Semana); pulado ≠ feito; no Google o dia some (EXDATE); no espelho fica tracejado e libera o horário |
| 6.2 | **Visão de mês** no app (depois, talvez página no espelho) | próximo |
| 6.3 | **Ordenar tarefas arrastando** dentro do projeto (campo `ordem` já existe; precisa funcionar no toque) | — |
| 6.4 | **Botão no Obsidian**: endpoint com token + comando no Obsidian (Shell Commands/QuickAdd) → `/api/planos/importar` | — |
| 6.5 | **Plano com IA**: objetivo → plano no formato do importador → prévia → importar. Decidir modelo/custo; ideia de um modelo especializado em planos | — |

### 6.1 — como funciona
- Recorrente na agenda: ✓ = fiz · ⏭ = pulei (não fiz e não vou fazer). ⏭ de novo desfaz; ✓ num dia pulado vira feito.
- Rotas: `POST /pular/{id}?dia=AAAA-MM-DD` (web) e `PUT /api/itens/{id}/ocorrencias` com `status: "pulado"` (API).
- Google: dias pulados viram `EXDATE` no evento recorrente.
- 92 testes passando. `ASSET_VERSION` = 9.

## Como retomar
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
