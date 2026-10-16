# App de Tarefas — Planejamento (Fase 5)

_Rascunho de 15/10/2026. Fonte da verdade da Fase 5; atualizar conforme as decisões._

## Objetivo
Um app próprio para planejar estudo, trabalho e vida pessoal, com links, progresso, anotações,
prioridade e recorrência, acessível pelo celular e pelo computador. O espelho mostra o que fazer
e quando; o Google Agenda recebe os compromissos com horário (para notificações no celular).

## Visão geral

```
 Celular / PC  ──(Tailscale, HTTPS)──►  Raspberry Pi
                                         ├── tarefas.service  (FastAPI + SQLite, porta 8090)
                                         │     ├── interface web (PWA: instalável na tela inicial)
                                         │     ├── API JSON  ──► espelho (páginas Início e Agenda)
                                         │     └── sincronização ──► Google Agenda (conta de serviço)
                                         └── magicmirror.service (já existente)
```

## Modelo de dados

### Area
Grandes divisões da vida. Editável pelo app.
| Campo | Tipo | Observação |
|---|---|---|
| id | int | |
| nome | str | Estudo, Trabalho, Pessoal, Lazer… |
| cor | str | hex, usada no app e no espelho |

### Projeto
Agrupa itens: um curso, uma matéria, um cliente, um objetivo pessoal.
| Campo | Tipo | Observação |
|---|---|---|
| id | int | |
| nome | str | "Linux — Alura", "Cliente X — Catálogo" |
| area_id | FK Area | |
| prioridade | enum | herdada pelos itens novos (pode ser alterada no item) |
| link | str? | página principal (curso, repositório…) |
| notas | text? | Markdown |
| progresso | ver "Progresso" | modos manual, quantidade ou **itens** |
| status | enum | ativo, pausado, concluído, arquivado |

### Item
A atividade em si.
| Campo | Tipo | Observação |
|---|---|---|
| id | int | |
| titulo | str | |
| tipo | enum | aula, atividade, tarefa, compromisso, hábito |
| projeto_id | FK Projeto? | opcional |
| area_id | FK Area | herdada do projeto quando houver |
| prioridade | enum | baixa · média · alta · crítica |
| status | enum | a fazer, em andamento, concluído, cancelado |
| inicio | datetime? | quando fazer (sem data → lista de pendências) |
| fim | datetime? | término previsto |
| dia_inteiro | bool | |
| prazo | datetime? | data-limite de entrega (diferente de quando fazer) |
| recorrencia | str? | regra RRULE (padrão iCalendar), ex.: `FREQ=WEEKLY;BYDAY=TU,TH` |
| progresso | ver "Progresso" | modos manual ou quantidade |
| notas | text? | Markdown |
| gcal_event_id | str? | controle da sincronização |
| criado_em / atualizado_em | datetime | |

### Link
| Campo | Tipo | Observação |
|---|---|---|
| id | int | |
| item_id **ou** projeto_id | FK | |
| rotulo | str | "Aula 12", "Enunciado", "Figma" |
| url | str | |

### Ocorrencia
Registro por dia de itens recorrentes ("fui à academia hoje?").
| Campo | Tipo | Observação |
|---|---|---|
| id | int | |
| item_id | FK Item | item recorrente |
| data | date | dia da ocorrência |
| status | enum | concluído, pulado, cancelado |
| nota | text? | ex.: "treino de pernas" |

As ocorrências **não** são pré-geradas: o app calcula as datas a partir da RRULE
(`python-dateutil`) e só grava uma linha quando algo acontece naquele dia.

## Progresso (Projeto e Item)

| Modo | Uso | Cálculo |
|---|---|---|
| `manual` | "~50% da implementação do cliente X" | valor 0–100 informado |
| `quantidade` | "4 h de 8 h do curso", "12 de 40 aulas" | `atual / total`, com `unidade` (h, aulas, páginas…) |
| `itens` (só Projeto) | projeto com aulas/tarefas cadastradas | itens concluídos / itens totais |
| `nenhum` | itens simples | — |

Campos: `progresso_modo`, `progresso_manual`, `progresso_atual`, `progresso_total`, `progresso_unidade`.
O percentual exibido é sempre calculado pelo backend.

## Prioridade
`baixa` (ex.: jogar FIFA) · `média` · `alta` · `crítica` (ex.: entrega para cliente).
- No app: ordenação padrão e cor do item.
- No espelho: cor/ícone na lista do dia; itens críticos sempre visíveis no Início.
- No Google Agenda: cor do evento (colorId) por prioridade.

## Interface (PWA)
- Uma única interface web, responsiva, servida pelo próprio FastAPI.
- **PWA**: no celular, "Adicionar à tela de início" cria um ícone que abre em tela cheia, como um
  app — sem loja, sem instalar nada. No PC, abre no navegador (ou também "instalar").
- Stack sugerida: **Jinja2 + HTMX + Alpine.js** — renderização no servidor, pouco JavaScript,
  nenhum passo de build, leve para o Pi e 100% dentro do stack Python.
- Telas iniciais: **Hoje** (agenda do dia + pendências por prioridade), **Semana**, **Projetos**,
  **Item** (edição com links, progresso e notas), **Captura rápida** (adicionar em 2 toques).

## Acesso e segurança
- **Tailscale** no Pi, no celular e no notebook: rede privada só com os seus aparelhos,
  funciona fora de casa, sem abrir portas no roteador.
- **HTTPS** via `tailscale serve` (necessário para recursos de PWA como o service worker).
- Sem tela de login na v1: só aparelhos da sua rede Tailscale enxergam o app.

## Google Agenda
- Agenda dedicada (ex.: "Espelho"), compartilhada com uma **conta de serviço** do Google Cloud
  (gratuita, sem cartão; token não expira como o OAuth em modo teste).
- Vão para a agenda só itens **com horário** (ou dia inteiro): título, horário, cor da prioridade
  e, na descrição, o link de volta para o item no app.
- Itens recorrentes → evento recorrente com a mesma RRULE.
- Sincronização em mão única (app → Google): na hora de salvar + conferência a cada 15 min.

## Espelho
- Lê a **API do app direto** (está no mesmo Pi): mais rico que o iCal (prioridade, progresso,
  ocorrências do dia) e independente do Google.
- Início: coluna "Hoje" com os próximos itens e horários (substitui o placeholder).
- Página Agenda: visões dia / semana / mês.

## Operação
- `systemd/tarefas.service` (uvicorn, porta 8090) — mesmo fluxo de deploy dos outros serviços.
- Banco em `data/tarefas.db` (fora do Git). Backup diário com `sqlite3 .backup` em `data/backups/`
  (mantém 14 dias); cópia manual para o notebook quando quiser.
- Desenvolvimento no notebook: `uvicorn` local com um banco de teste.

## Estrutura no repo
```
tarefas/
├── app/
│   ├── main.py          # FastAPI, montagem das rotas
│   ├── db.py            # engine SQLite, sessão
│   ├── models.py        # SQLModel (Area, Projeto, Item, Link, Ocorrencia)
│   ├── schemas.py       # entrada/saída da API (Pydantic)
│   ├── services/
│   │   ├── progresso.py
│   │   ├── recorrencia.py
│   │   └── gcal.py
│   ├── routers/         # api (JSON) e web (HTML)
│   ├── templates/       # Jinja2 + HTMX
│   └── static/          # CSS, manifest.json, service worker, ícones
├── tests/
└── requirements.txt
```

## Etapas
1. **5.1 Backend** ✅: modelos, API JSON (CRUD + "itens do dia"), progresso e recorrência, testes.
2. **5.2 Interface** ✅: telas Hoje, Semana, Projetos, Item, Áreas e captura rápida; PWA (manifest, service worker, ícones).
   - **5.2.1** ✅: hierarquia de projetos (subprojetos, trilha, herança), progresso automático em cascata
     (ponderado pela duração), etapas sequenciais, duração estimada, botão +1, notas em Markdown,
     "Repetir" sempre visível, prioridade baixa discreta, migração automática de colunas.
   - **5.2.2** ✅: importador de planejamento (Obsidian → app): modelo `.md`, prompt pronto para IA
     (criar/converter), prévia e reimportação sem duplicar. Ver "Planejamento" abaixo.
   - **5.2.3** ✅: agendar etapa: tarefas da etapa liberada encaixadas nos horários de estudo
     (dias, hora, duração da sessão), na ordem do plano, desviando do que já está na agenda;
     atrasadas: remarcar nos espaços livres ou empurrar as seguintes (mantendo a ordem), também
     direto na Hoje (botão 📅 na tarefa atrasada); desagendar; horários guardados no plano e sugestão quando a próxima
     etapa libera (na Hoje e no projeto).
3. **5.3 Deploy no Pi**: serviço systemd, Tailscale, `tailscale serve`, backup.
4. **5.4 Google Agenda**: conta de serviço, agenda dedicada, sincronização.
5. **5.5 Espelho**: coluna "Hoje" na Início e página Agenda.

## Planejamento (Obsidian → app)
- Fonte: uma nota `Planejamento.md` no Obsidian, num formato simples (frontmatter `projeto`, `area`,
  `sequencial`; `##` = etapa/subprojeto; `- [ ]` = item; `| 1h` = duração; `[rótulo](url)` = link;
  `| 3 de 5` = quantidade; `- [x]` = concluído; o resto é anotação livre).
- Tela "Importar plano": **Copiar modelo**, **Copiar prompt para a IA** (criar ou converter/atualizar)
  e **Importar** (colar ou enviar o `.md` → prévia → confirmar). Modelo, prompt e importador saem da
  mesma especificação.
- Reimportar atualiza pelo nome (não duplica) e preserva progresso e conclusões feitas no app.
- Cada projeto importado ganha um link "Planejamento" que abre a nota no Obsidian (`obsidian://`).

## Ideias para depois (combinadas, não esquecer)
- **Botão no Obsidian** ("Enviar para a Agenda"): plugin pequeno que manda a nota direto para a API
  do Pi via Tailscale.
- **Geração do plano com IA**: descrever o objetivo ("piano do zero, 3 h/semana, 10 semanas") e
  receber o planejamento já no formato do importador, com etapas, durações e fontes; idealmente um
  "modelo" (prompt/assistente) especializado em montar planejamentos de estudo de qualidade.
- Marcar ocorrência de recorrente como "pulado"; visão de mês; ordem manual por arrastar.
