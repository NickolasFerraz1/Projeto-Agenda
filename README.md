# Projeto Agenda

App pessoal de tarefas: projetos, itens com links, progresso, prioridade, prazos e
recorrência. Backend FastAPI + SQLModel (SQLite). Roda no Raspberry Pi do Magic Mirror,
acessado pelo celular e pelo PC via Tailscale. Planejamento completo em
[`docs/APP-TAREFAS.md`](docs/APP-TAREFAS.md).

## Rodar localmente

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8090
```

- Interface (app): http://localhost:8090
- Documentação interativa da API: http://localhost:8090/docs
- Banco: `data/agenda.db` (criado no primeiro uso, fora do Git). Outro caminho: variável `AGENDA_DB`.
  Colunas novas dos modelos são acrescentadas sozinhas na inicialização (`db._migrar_colunas`).

## Interface (PWA)

Páginas renderizadas no servidor (Jinja2) com HTMX e Alpine.js, sem passo de build
(os dois ficam em `app/static/vendor/`).

| Tela | Rota | O que tem |
|---|---|---|
| Hoje | `/` | captura rápida, agenda do dia, atrasados e pendências; toque no círculo marca como feito |
| Semana | `/semana` | 7 dias (seg–dom), navegação entre semanas, "+" cria item no dia |
| Projetos | `/projetos` | cartões com progresso; detalhe com links, notas e itens |
| Item | `/itens/{id}`, `/itens/novo` | edição completa: quando, repetição, prazo, progresso, links, notas |
| Áreas | `/areas` | nome e cor de cada área |
| Agendar | `/projetos/{id}/agendar` | distribui as tarefas da etapa nos horários de estudo (prévia; atrasadas: espaços livres ou empurrar as seguintes; desagendar) |
| Importar plano | `/importar` | planejamento em Markdown (Obsidian) → projeto, etapas e tarefas; modelo e prompts para IA |

- **Projetos em níveis** (Pós FIAP › Fase 3 › Bloco › aulas): cada projeto pode ter subprojetos.
  Subprojeto herda área e prioridade do pai. Excluir um projeto sobe os filhos um nível.
- **Progresso automático** (padrão dos projetos): média dos itens e subprojetos; ponderada pela
  duração estimada quando todos os filhos têm duração. Item com "3 de 5" conta 60%.
- **Sequencial**: os subprojetos liberam um de cada vez (Semana 1 → 2 → 3). Itens de etapas
  travadas e de projetos pausados/arquivados não aparecem nas pendências.
- **Agendar etapa**: distribui as tarefas nos horários de estudo; num plano sequencial, pode
  **agendar sozinho** a próxima etapa quando a anterior termina (aviso na tela).
- **+1** nos itens com progresso por quantidade; ao chegar no total, o item é concluído.
- **Notas em Markdown**, com pré-visualização.
- Itens recorrentes: marcar na agenda vale **só para aquele dia** (registro de ocorrência).
- Repetição por presets (todo dia, dias úteis, dias da semana, todo mês, até uma data) ou RRULE personalizada.
- **Instalar no celular**: abrir o app no navegador → "Adicionar à tela de início". O service worker
  exige HTTPS (no Pi, via `tailscale serve`) ou `localhost`.
- Mudou CSS/JS/ícones? Incremente `ASSET_VERSION` em `app/config.py` para renovar o cache do PWA.
- Ícones: `python scripts/gerar_icones.py` (precisa de `pillow`).

## Planejamento (Obsidian → app)

Formato completo em `/importar` ("Ver o formato completo") ou `GET /api/planos/formato`. Resumo:

```markdown
---
projeto: Piano
area: Estudo
sequencial: true
---
## Semana 1
Meta da semana: postura.
- [ ] Postura e posição das mãos | 1h | [vídeo](https://...)
- [ ] Escala de Dó | 30min | 0 de 3 repetições | !alta
```

Reimportar atualiza pelo nome, não duplica, nunca apaga e mantém o que foi concluído/progredido no app.

## Deploy no Raspberry Pi

O app roda como serviço `systemd` (`agenda.service`, porta 8090, só `127.0.0.1`) e é acessado
de fora pelo **Tailscale** com HTTPS (`tailscale serve`). Backup diário às 03:30 em
`data/backups/` (mantém 14).

```bash
# primeira vez
cd ~ && git clone https://github.com/NickolasFerraz1/Projeto-Agenda.git projeto-agenda
cd projeto-agenda && bash scripts/instalar_pi.sh

# atualizar depois de um git push no PC
cd ~/projeto-agenda && git pull && bash scripts/instalar_pi.sh
```

| Comando | Para quê |
|---|---|
| `systemctl status agenda` | o app está rodando? |
| `journalctl -u agenda -n 50 --no-pager` | últimos logs |
| `sudo systemctl restart agenda` | reiniciar |
| `systemctl list-timers agenda-backup.timer` | próximo backup |
| `tailscale serve status` | endereço HTTPS do app |

## Testes

```bash
pytest -q
```

## API (resumo)

| Método | Rota | Descrição |
|---|---|---|
| GET/POST | `/api/areas` | listar / criar áreas |
| PATCH/DELETE | `/api/areas/{id}` | editar / excluir (só se não estiver em uso) |
| GET/POST | `/api/projetos` | listar (filtros `area_id`, `status`, `pai_id`, `raiz=true`) / criar (`pai_id` = subprojeto) |
| GET/PATCH/DELETE | `/api/projetos/{id}` | obter / editar / excluir (itens ficam sem projeto) |
| GET | `/api/projetos/{id}/itens` | itens do projeto |
| GET/POST | `/api/itens` | listar (filtros `projeto_id`, `area_id`, `status`, `tipo`, `sem_data`) / criar |
| GET/PATCH/DELETE | `/api/itens/{id}` | obter / editar / excluir |
| GET/PUT | `/api/itens/{id}/ocorrencias` | registros diários de um item recorrente / marcar um dia |
| DELETE | `/api/itens/{id}/ocorrencias/{data}` | desfazer o registro do dia |
| GET | `/api/agenda?de=AAAA-MM-DD&ate=AAAA-MM-DD` | agendados, ocorrências de recorrentes e prazos |
| GET | `/api/hoje` | agenda de hoje + atrasados + pendências sem data |
| GET | `/api/planos/modelo`, `/api/planos/formato`, `/api/planos/prompt?modo=criar\|converter` | modelo, especificação e prompts do planejamento (texto) |
| POST | `/api/projetos/{id}/agendar` | `{"dias": ["MO","WE","FR"], "hora": "19:00", "minutos": 60, "simular": true}` |
| POST | `/remarcar/{item_id}?modo=so\|empurrar` | (interface) remarca uma tarefa atrasada nos horários do plano |
| POST | `/api/projetos/{id}/desagendar` | tarefas em aberto de hoje em diante voltam para "sem data" |
| POST | `/api/planos/previa`, `/api/planos/importar` | `{"texto": "..."}`: simula / importa um planejamento |

Horários são locais, sem fuso (ex.: `2026-10-20T19:00`). Recorrência no padrão RRULE do
iCalendar (ex.: `FREQ=WEEKLY;BYDAY=TU,TH`); o `inicio` do item define o horário e o primeiro dia.
