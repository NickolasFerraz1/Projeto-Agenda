"""Formatos de entrada e saída da API."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NaiveDatetime, field_validator, model_validator

from app.models import (
	Prioridade,
	ProgressoModo,
	StatusItem,
	StatusOcorrencia,
	StatusProjeto,
	TipoItem,
)
from app.services import recorrencia


# ---------- Comuns ----------
class LinkIn(BaseModel):
	rotulo: str = Field(max_length=80)
	url: str


class LinkOut(LinkIn):
	id: int


class ProgressoIn(BaseModel):
	progresso_modo: ProgressoModo | None = None
	progresso_manual: float | None = Field(default=None, ge=0, le=100)
	progresso_atual: float | None = Field(default=None, ge=0)
	progresso_total: float | None = Field(default=None, gt=0)
	progresso_unidade: str | None = Field(default=None, max_length=20)


class ProgressoOut(BaseModel):
	progresso_modo: ProgressoModo
	progresso_manual: float | None
	progresso_atual: float | None
	progresso_total: float | None
	progresso_unidade: str | None
	progresso: float | None = None  # percentual calculado


# ---------- Área ----------
class AreaIn(BaseModel):
	nome: str = Field(max_length=40)
	cor: str = Field(default="#999999", pattern=r"^#[0-9a-fA-F]{6}$")


class AreaUpdate(BaseModel):
	nome: str | None = Field(default=None, max_length=40)
	cor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class AreaOut(AreaIn):
	model_config = ConfigDict(from_attributes=True)
	id: int


# ---------- Projeto ----------
class ProjetoIn(ProgressoIn):
	nome: str = Field(max_length=120)
	pai_id: int | None = None  # subprojeto de outro projeto
	area_id: int | None = None  # herda do pai quando omitida
	prioridade: Prioridade | None = None  # herda do pai quando omitida (padrão: média)
	ordem: int = 0
	sequencial: bool = False
	agenda_dias: str | None = Field(default=None, pattern=r"^(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*$")
	agenda_hora: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
	agenda_minutos: int | None = Field(default=None, ge=10, le=12 * 60)
	agenda_auto: bool = False
	status: StatusProjeto = StatusProjeto.ativo
	link: str | None = None
	notas: str | None = None
	links: list[LinkIn] = []


class ProjetoUpdate(ProgressoIn):
	nome: str | None = Field(default=None, max_length=120)
	pai_id: int | None = None
	agenda_dias: str | None = Field(default=None, pattern=r"^(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*$")
	agenda_hora: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
	agenda_minutos: int | None = Field(default=None, ge=10, le=12 * 60)
	agenda_auto: bool | None = None
	area_id: int | None = None
	ordem: int | None = None
	sequencial: bool | None = None
	prioridade: Prioridade | None = None
	status: StatusProjeto | None = None
	link: str | None = None
	notas: str | None = None
	links: list[LinkIn] | None = None  # se enviado, substitui a lista inteira


class ProjetoOut(ProgressoOut):
	id: int
	nome: str
	pai_id: int | None
	caminho: str = ""  # "Pós FIAP › Fase 3 › CI/CD"
	ordem: int
	sequencial: bool
	ordem_manual: bool = False  # filhos reordenados à mão (arrastar)
	bloqueado: bool = False  # travado por um pai sequencial
	agenda_dias: str | None = None  # horários de estudo (Agendar)
	agenda_hora: str | None = None
	agenda_minutos: int | None = None
	agenda_auto: bool = False
	area_id: int
	prioridade: Prioridade
	status: StatusProjeto
	link: str | None
	notas: str | None
	links: list[LinkOut] = []
	criado_em: datetime
	atualizado_em: datetime


class OrdenarIn(BaseModel):
	"""Nova ordem dos filhos de um projeto (arrastar na página do projeto)."""

	tipo: Literal["itens", "subprojetos"]
	ids: list[int] = Field(min_length=1)


class AgendarIn(BaseModel):
	dias: list[str] = Field(min_length=1)  # ["MO", "WE", "FR"]
	hora: str = Field(pattern=r"^\d{2}:\d{2}$")  # "19:00"
	minutos: int = Field(ge=10, le=12 * 60)  # duração de cada sessão
	a_partir: date | None = None
	remarcar: bool = True  # inclui tarefas agendadas no passado e não feitas
	empurrar: bool = False  # redistribui também as já marcadas no futuro, mantendo a ordem
	simular: bool = False  # True = só prévia
	auto: bool | None = None  # liga/desliga "agendar a próxima etapa sozinho" no plano

	@field_validator("dias")
	@classmethod
	def _dias(cls, v):
		validos = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}
		if any(d not in validos for d in v):
			raise ValueError("dias: use MO, TU, WE, TH, FR, SA, SU")
		return v


# ---------- Item ----------
class _ItemValidacao(BaseModel):
	@field_validator("recorrencia", check_fields=False)
	@classmethod
	def _rrule(cls, v):
		if v in (None, ""):
			return None
		try:
			return recorrencia.validar(v)
		except (ValueError, TypeError) as exc:
			raise ValueError(f"recorrência inválida: {exc}") from exc

	@model_validator(mode="after")
	def _datas(self):
		inicio, fim = getattr(self, "inicio", None), getattr(self, "fim", None)
		if inicio and fim and fim < inicio:
			raise ValueError("fim não pode ser antes do início")
		return self


class ItemIn(ProgressoIn, _ItemValidacao):
	titulo: str = Field(max_length=200)
	tipo: TipoItem = TipoItem.tarefa
	projeto_id: int | None = None
	area_id: int | None = None  # herda do projeto quando omitida
	prioridade: Prioridade | None = None  # herda do projeto quando omitida
	status: StatusItem = StatusItem.a_fazer
	inicio: NaiveDatetime | None = None  # horário local, sem fuso
	fim: NaiveDatetime | None = None  # horário local, sem fuso
	dia_inteiro: bool = False
	prazo: NaiveDatetime | None = None  # horário local, sem fuso
	recorrencia: str | None = None
	duracao_min: int | None = Field(default=None, ge=1)  # duração estimada, em minutos
	ordem: int = 0
	notas: str | None = None
	links: list[LinkIn] = []

	@model_validator(mode="after")
	def _recorrente_tem_inicio(self):
		if self.recorrencia and not self.inicio:
			raise ValueError("item recorrente precisa de início (define o horário e o 1º dia)")
		return self


class ItemUpdate(ProgressoIn, _ItemValidacao):
	titulo: str | None = Field(default=None, max_length=200)
	tipo: TipoItem | None = None
	projeto_id: int | None = None
	area_id: int | None = None
	prioridade: Prioridade | None = None
	status: StatusItem | None = None
	inicio: NaiveDatetime | None = None  # horário local, sem fuso
	fim: NaiveDatetime | None = None  # horário local, sem fuso
	dia_inteiro: bool | None = None
	prazo: NaiveDatetime | None = None  # horário local, sem fuso
	recorrencia: str | None = None
	duracao_min: int | None = Field(default=None, ge=1)
	ordem: int | None = None
	notas: str | None = None
	links: list[LinkIn] | None = None


class ItemOut(ProgressoOut):
	id: int
	titulo: str
	tipo: TipoItem
	projeto_id: int | None
	area_id: int
	prioridade: Prioridade
	status: StatusItem
	inicio: datetime | None
	fim: datetime | None
	dia_inteiro: bool
	prazo: datetime | None
	recorrencia: str | None
	duracao_min: int | None
	ordem: int
	notas: str | None
	links: list[LinkOut] = []
	criado_em: datetime
	atualizado_em: datetime


# ---------- Ocorrência ----------
class OcorrenciaIn(BaseModel):
	data: date
	status: StatusOcorrencia = StatusOcorrencia.concluido
	nota: str | None = None


class OcorrenciaOut(OcorrenciaIn):
	model_config = ConfigDict(from_attributes=True)
	id: int
	item_id: int


# ---------- Agenda ----------
class Entrada(BaseModel):
	"""Uma linha da agenda: um item (ou uma ocorrência dele) num dia."""

	tipo_entrada: str  # "agendado" | "prazo"
	item_id: int
	titulo: str
	tipo: TipoItem
	data: date
	inicio: datetime | None
	fim: datetime | None
	dia_inteiro: bool
	prioridade: Prioridade
	status: str  # status do item, ou da ocorrência no dia (concluido/pulado/a_fazer)
	recorrente: bool
	area_id: int
	area_nome: str
	area_cor: str
	projeto_id: int | None
	projeto_nome: str | None
	projeto_caminho: str | None = None  # "Piano › Semana 2"
	ocorrencia_data: date | None = None  # recorrente: dia original da ocorrência (ações ✓/⏭/mover usam este)
	movida: bool = False  # recorrente movida só neste dia
	duracao_min: int | None = None
	progresso: float | None


class Hoje(BaseModel):
	data: date
	agenda: list[Entrada]  # o que está marcado para hoje (inclui prazos de hoje)
	atrasados: list[ItemOut]  # não recorrentes, marcados antes de hoje e não concluídos
	pendencias: list[ItemOut]  # sem data, não concluídos, por prioridade e prazo
