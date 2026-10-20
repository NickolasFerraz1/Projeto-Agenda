"""Tabelas do banco (SQLModel = Pydantic + SQLAlchemy)."""
from datetime import date, datetime

# Horários sem fuso: tudo no horário local do usuário (ver config.TIMEZONE).
from enum import Enum

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


# ---------- Enumerações ----------
class Prioridade(str, Enum):
	baixa = "baixa"
	media = "media"
	alta = "alta"
	critica = "critica"

	@property
	def peso(self) -> int:  # para ordenação: crítica primeiro
		return {"baixa": 1, "media": 2, "alta": 3, "critica": 4}[self.value]


class TipoItem(str, Enum):
	aula = "aula"
	atividade = "atividade"
	tarefa = "tarefa"
	compromisso = "compromisso"
	habito = "habito"


class StatusItem(str, Enum):
	a_fazer = "a_fazer"
	em_andamento = "em_andamento"
	concluido = "concluido"
	cancelado = "cancelado"


class StatusProjeto(str, Enum):
	ativo = "ativo"
	pausado = "pausado"
	concluido = "concluido"
	arquivado = "arquivado"


class ProgressoModo(str, Enum):
	nenhum = "nenhum"
	manual = "manual"  # "~50% da implementação"
	quantidade = "quantidade"  # "4 h de 8 h", "12 de 40 aulas"
	itens = "itens"  # só Projeto: automático, média dos itens e subprojetos (ponderada pela duração)


class StatusOcorrencia(str, Enum):
	concluido = "concluido"
	pulado = "pulado"


# ---------- Mixins ----------
class ProgressoCampos(SQLModel):
	progresso_modo: ProgressoModo = ProgressoModo.nenhum
	progresso_manual: float | None = Field(default=None, ge=0, le=100)
	progresso_atual: float | None = Field(default=None, ge=0)
	progresso_total: float | None = Field(default=None, gt=0)
	progresso_unidade: str | None = Field(default=None, max_length=20)


class Timestamps(SQLModel):
	criado_em: NaiveDatetime = Field(default_factory=datetime.now)
	atualizado_em: NaiveDatetime = Field(default_factory=datetime.now)


# ---------- Tabelas ----------
class Area(SQLModel, table=True):
	id: int | None = Field(default=None, primary_key=True)
	nome: str = Field(max_length=40, unique=True)
	cor: str = Field(default="#999999", max_length=9)


class Projeto(ProgressoCampos, Timestamps, table=True):
	id: int | None = Field(default=None, primary_key=True)
	nome: str = Field(max_length=120)
	pai_id: int | None = Field(default=None, foreign_key="projeto.id", index=True, ondelete="SET NULL")  # subprojeto
	ordem: int = 0  # posição entre os irmãos (0 = ordem natural pelo nome)
	sequencial: bool = False  # subprojetos liberam um de cada vez, na ordem
	ordem_manual: bool = False  # filhos reordenados à mão no app: reimportar o plano não mexe na ordem
	progresso_modo: ProgressoModo = ProgressoModo.itens  # projetos: automático por padrão
	# Horários de estudo para "Agendar" (guardados no plano e herdados pelas etapas)
	agenda_dias: str | None = None  # "MO,WE,FR"
	agenda_hora: str | None = None  # "19:00"
	agenda_minutos: int | None = None  # duração de cada sessão
	agenda_auto: bool = False  # sequencial: agenda sozinho a próxima etapa quando a anterior termina
	area_id: int = Field(foreign_key="area.id", index=True)
	prioridade: Prioridade = Prioridade.media
	status: StatusProjeto = StatusProjeto.ativo
	link: str | None = None
	notas: str | None = None


class Item(ProgressoCampos, Timestamps, table=True):
	id: int | None = Field(default=None, primary_key=True)
	titulo: str = Field(max_length=200)
	tipo: TipoItem = TipoItem.tarefa
	projeto_id: int | None = Field(default=None, foreign_key="projeto.id", index=True, ondelete="SET NULL")
	area_id: int = Field(foreign_key="area.id", index=True)
	prioridade: Prioridade = Prioridade.media
	status: StatusItem = StatusItem.a_fazer
	inicio: NaiveDatetime | None = Field(default=None, index=True)  # quando fazer
	fim: NaiveDatetime | None = None
	dia_inteiro: bool = False
	prazo: NaiveDatetime | None = Field(default=None, index=True)  # data-limite de entrega
	recorrencia: str | None = None  # RRULE, ex.: "FREQ=WEEKLY;BYDAY=TU,TH"
	duracao_min: int | None = Field(default=None, ge=1)  # duração estimada (pesa no progresso do projeto)
	ordem: int = 0  # posição dentro do projeto (0 = ordem natural pelo título)
	notas: str | None = None
	gcal_event_id: str | None = None


class Link(SQLModel, table=True):
	id: int | None = Field(default=None, primary_key=True)
	item_id: int | None = Field(default=None, foreign_key="item.id", index=True, ondelete="CASCADE")
	projeto_id: int | None = Field(default=None, foreign_key="projeto.id", index=True, ondelete="CASCADE")
	rotulo: str = Field(max_length=80)
	url: str


class Ocorrencia(SQLModel, table=True):
	"""Registro por dia de um item recorrente. Só existe quando algo aconteceu no dia."""

	id: int | None = Field(default=None, primary_key=True)
	item_id: int = Field(foreign_key="item.id", index=True, ondelete="CASCADE")
	data: date = Field(index=True)
	status: StatusOcorrencia
	nota: str | None = None
