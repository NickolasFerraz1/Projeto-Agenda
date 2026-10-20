"""Sincronização app -> Google Agenda (mão única), por reconciliação.

A cada rodada: monta o conjunto de eventos que DEVERIAM existir (a partir dos itens) e
compara com os eventos da agenda dedicada (marcados com extendedProperties "origem=agenda").
Cria o que falta, atualiza o que mudou (hash) e apaga o que sobrou. Não guarda estado no
banco: se algo se perder, a próxima rodada conserta.

- Item com horário (ou dia inteiro) e em aberto -> evento (cor pela prioridade).
- Recorrente -> evento recorrente com a mesma RRULE; dias pulados/movidos saem (EXDATE) e
  cada ocorrência movida vira um evento avulso ("mov:<id>:<AAAAMMDD>").
- Concluído -> fica na agenda com "✓" e sem lembretes. Cancelado ou sem data -> sai.
- Prazo de item em aberto -> evento "⏰ Prazo: …".
"""
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from datetime import time as hora
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app import config
from app.models import Area, Item, Ocorrencia, Prioridade, StatusItem, StatusOcorrencia
from app.services.progresso import Arvore

log = logging.getLogger("agenda.gcal")

DURACAO_PADRAO = timedelta(minutes=30)
DURACAO_PRAZO = timedelta(minutes=15)
CORES = {  # colorId do Google Agenda
	Prioridade.critica: "11",  # vermelho (tomate)
	Prioridade.alta: "6",  # laranja (tangerina)
	Prioridade.media: "9",  # azul (mirtilo)
	Prioridade.baixa: "8",  # cinza (grafite)
}
API = "https://www.googleapis.com/calendar/v3"


# ---------------------------------------------------------------------------
# Eventos desejados (puro, sem rede)
# ---------------------------------------------------------------------------
def _until_utc(regra: str, dia_inteiro: bool) -> str:
	"""O Google exige UNTIL em UTC (…Z) para eventos com horário e só data para dia inteiro."""
	partes = []
	for p in regra.split(";"):
		if p.startswith("UNTIL="):
			valor = p[6:]
			try:
				local = datetime.strptime(valor[:15], "%Y%m%dT%H%M%S")
			except ValueError:
				partes.append(p)
				continue
			if dia_inteiro:
				p = f"UNTIL={local:%Y%m%d}"
			else:
				utc = local.replace(tzinfo=ZoneInfo(config.TIMEZONE)).astimezone(timezone.utc)
				p = f"UNTIL={utc:%Y%m%dT%H%M%SZ}"
		partes.append(p)
	return ";".join(partes)


def _exdate(dias: list, inicio: datetime, dia_inteiro: bool) -> str:
	"""Dias pulados de um recorrente: EXDATE no mesmo formato do início do evento."""
	if dia_inteiro:
		return "EXDATE;VALUE=DATE:" + ",".join(f"{d:%Y%m%d}" for d in dias)
	return f"EXDATE;TZID={config.TIMEZONE}:" + ",".join(f"{d:%Y%m%d}T{inicio:%H%M%S}" for d in dias)


def _quando(inicio: datetime, fim: datetime | None, dia_inteiro: bool, padrao: timedelta) -> dict:
	if dia_inteiro:
		return {"start": {"date": inicio.date().isoformat()}, "end": {"date": (inicio.date() + timedelta(days=1)).isoformat()}}
	fim = fim if fim and fim > inicio else inicio + padrao
	tz = config.TIMEZONE
	return {
		"start": {"dateTime": inicio.isoformat(timespec="seconds"), "timeZone": tz},
		"end": {"dateTime": fim.isoformat(timespec="seconds"), "timeZone": tz},
	}


def _descricao(item: Item, contexto: str) -> str:
	linhas = [contexto] if contexto else []
	if item.notas:
		linhas += ["", item.notas]
	linhas += ["", f"Abrir no app: {config.URL_APP}/itens/{item.id}"]
	return "\n".join(linhas)


def eventos_desejados(session: Session) -> dict[str, dict]:
	"""{chave: corpo do evento}. Chave = "item:<id>" ou "prazo:<id>"."""
	arv = Arvore.carregar(session)
	areas = {a.id: a.nome for a in session.exec(select(Area)).all()}
	# Recorrentes: dias pulados ou movidos saem da série (EXDATE); a movida vira um evento avulso
	pulados: dict[int, list] = {}
	movidas: list[Ocorrencia] = []
	for oc in session.exec(select(Ocorrencia).order_by(Ocorrencia.data)).all():
		if oc.status == StatusOcorrencia.pulado or oc.inicio:
			pulados.setdefault(oc.item_id, []).append(oc.data)
		if oc.inicio and oc.status != StatusOcorrencia.pulado:
			movidas.append(oc)
	desejados: dict[str, dict] = {}
	for it in session.exec(select(Item).where(Item.status != StatusItem.cancelado)).all():
		contexto = arv.caminho_texto(it.projeto_id) if it.projeto_id else areas.get(it.area_id, "")
		feito = it.status == StatusItem.concluido
		if it.inicio:
			corpo = {
				"summary": ("✓ " if feito else "") + it.titulo,
				"description": _descricao(it, contexto),
				"colorId": "8" if feito else CORES[it.prioridade],
				"reminders": {"useDefault": False, "overrides": []} if feito else {"useDefault": True},
				**_quando(it.inicio, it.fim or (it.inicio + timedelta(minutes=it.duracao_min) if it.duracao_min else None), it.dia_inteiro, DURACAO_PADRAO),
			}
			if it.recorrencia:
				corpo["recurrence"] = ["RRULE:" + _until_utc(it.recorrencia, it.dia_inteiro)]
				if pulados.get(it.id):
					corpo["recurrence"].append(_exdate(pulados[it.id], it.inicio, it.dia_inteiro))
			desejados[f"item:{it.id}"] = corpo
		if it.recorrencia and it.inicio:
			for oc in (o for o in movidas if o.item_id == it.id):
				oc_feito = oc.status == StatusOcorrencia.concluido
				desejados[f"mov:{it.id}:{oc.data:%Y%m%d}"] = {
					"summary": ("✓ " if oc_feito else "") + it.titulo,
					"description": _descricao(it, contexto),
					"colorId": "8" if oc_feito else CORES[it.prioridade],
					"reminders": {"useDefault": False, "overrides": []} if oc_feito else {"useDefault": True},
					**_quando(oc.inicio, oc.fim, it.dia_inteiro, DURACAO_PADRAO),
				}
		if it.prazo and not feito:
			sem_hora = it.prazo.time() == hora(23, 59)  # prazo sem hora = o dia todo
			desejados[f"prazo:{it.id}"] = {
				"summary": f"⏰ Prazo: {it.titulo}",
				"description": _descricao(it, contexto),
				"colorId": CORES[it.prioridade],
				"reminders": {"useDefault": True},
				**_quando(it.prazo, None, sem_hora, DURACAO_PRAZO),
			}
	for chave, corpo in desejados.items():
		corpo["extendedProperties"] = {"private": {"origem": "agenda", "chave": chave, "hash": _hash(corpo)}}
	return desejados


def _hash(corpo: dict) -> str:
	base = {k: v for k, v in corpo.items() if k != "extendedProperties"}
	return hashlib.sha1(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Cliente do Google (REST + conta de serviço)
# ---------------------------------------------------------------------------
class ClienteGoogle:
	"""Chamadas mínimas da API do Google Agenda. Trocável nos testes por um falso."""

	def __init__(self, calendario: str, credenciais_json):
		from google.auth.transport.requests import AuthorizedSession
		from google.oauth2 import service_account

		cred = service_account.Credentials.from_service_account_file(
			str(credenciais_json), scopes=["https://www.googleapis.com/auth/calendar.events"]
		)
		self.http = AuthorizedSession(cred)
		self.base = f"{API}/calendars/{requests_quote(calendario)}/events"

	def _ok(self, r):
		if r.status_code >= 400:
			raise RuntimeError(f"Google {r.status_code}: {r.text[:300]}")
		return r.json() if r.content else None

	def listar(self) -> list[dict]:
		eventos, token = [], None
		while True:
			params = {"privateExtendedProperty": "origem=agenda", "maxResults": 2500, "showDeleted": "false"}
			if token:
				params["pageToken"] = token
			dados = self._ok(self.http.get(self.base, params=params, timeout=30))
			eventos += dados.get("items", [])
			token = dados.get("nextPageToken")
			if not token:
				return eventos

	def criar(self, corpo: dict) -> None:
		self._ok(self.http.post(self.base, json=corpo, timeout=30))

	def atualizar(self, event_id: str, corpo: dict) -> None:
		self._ok(self.http.put(f"{self.base}/{event_id}", json=corpo, timeout=30))

	def apagar(self, event_id: str) -> None:
		r = self.http.delete(f"{self.base}/{event_id}", timeout=30)
		if r.status_code not in (200, 204, 404, 410):
			self._ok(r)


def requests_quote(texto: str) -> str:
	from urllib.parse import quote

	return quote(texto, safe="")


# ---------------------------------------------------------------------------
# Reconciliação
# ---------------------------------------------------------------------------
@dataclass
class Resultado:
	criados: int = 0
	atualizados: int = 0
	apagados: int = 0
	total: int = 0
	erros: list[str] = field(default_factory=list)


def sincronizar(session: Session, cliente) -> Resultado:
	res = Resultado()
	desejados = eventos_desejados(session)
	existentes: dict[str, dict] = {}
	for ev in cliente.listar():
		chave = ev.get("extendedProperties", {}).get("private", {}).get("chave")
		if not chave or chave in existentes:  # duplicado (ex.: rodada interrompida): apaga
			try:
				cliente.apagar(ev["id"])
				res.apagados += 1
			except Exception as exc:  # noqa: BLE001
				res.erros.append(str(exc))
			continue
		existentes[chave] = ev
	for chave, corpo in desejados.items():
		try:
			ev = existentes.pop(chave, None)
			if ev is None:
				cliente.criar(corpo)
				res.criados += 1
			elif ev.get("extendedProperties", {}).get("private", {}).get("hash") != corpo["extendedProperties"]["private"]["hash"]:
				cliente.atualizar(ev["id"], corpo)
				res.atualizados += 1
		except Exception as exc:  # noqa: BLE001
			res.erros.append(f"{chave}: {exc}")
	for chave, ev in existentes.items():  # sobraram: item apagado, cancelado, sem data…
		try:
			cliente.apagar(ev["id"])
			res.apagados += 1
		except Exception as exc:  # noqa: BLE001
			res.erros.append(f"{chave}: {exc}")
	res.total = len(desejados)
	return res


# ---------------------------------------------------------------------------
# Execução em segundo plano: periódica + logo após mudanças (com espera de 3 s)
# ---------------------------------------------------------------------------
@dataclass
class Estado:
	configurado: bool = False
	ultima: datetime | None = None
	resultado: Resultado | None = None
	erro: str | None = None
	rodando: bool = False


ESTADO = Estado()
_acordar = threading.Event()
_parar = threading.Event()
_trava = threading.Lock()
_fabrica_cliente = None  # callable() -> cliente; definido em iniciar() (ou pelos testes)


def configurado() -> bool:
	return bool(config.GCAL_ID) and config.GCAL_CRED.exists()


def rodar_agora() -> Resultado | None:
	"""Uma rodada completa (com trava). Usada pelo laço e pelo botão "Sincronizar agora"."""
	from app import db

	if _fabrica_cliente is None:
		return None
	with _trava:
		ESTADO.rodando = True
		try:
			with Session(db.engine) as s:
				res = sincronizar(s, _fabrica_cliente())
			ESTADO.resultado, ESTADO.ultima = res, datetime.now()
			ESTADO.erro = "; ".join(res.erros[:3]) if res.erros else None
			log.info("gcal: +%d ~%d -%d (%d eventos)", res.criados, res.atualizados, res.apagados, res.total)
			return res
		except Exception as exc:  # noqa: BLE001
			ESTADO.erro, ESTADO.ultima = str(exc), datetime.now()
			log.warning("gcal: falhou: %s", exc)
			return None
		finally:
			ESTADO.rodando = False


def _laco() -> None:
	while not _parar.is_set():
		rodar_agora()
		acordou = _acordar.wait(timeout=config.GCAL_INTERVALO)
		if acordou:
			time.sleep(3)  # junta várias mudanças seguidas numa rodada só
			_acordar.clear()


def avisar_mudanca() -> None:
	"""Chamado depois de qualquer alteração (middleware): antecipa a próxima rodada."""
	if ESTADO.configurado:
		_acordar.set()


def iniciar() -> None:
	global _fabrica_cliente
	ESTADO.configurado = configurado()
	if not ESTADO.configurado:
		if config.GCAL_ID:
			log.warning("gcal: AGENDA_GCAL_ID definido, mas não achei %s", config.GCAL_CRED)
		return
	_fabrica_cliente = lambda: ClienteGoogle(config.GCAL_ID, config.GCAL_CRED)  # noqa: E731
	_parar.clear()
	threading.Thread(target=_laco, name="gcal-sync", daemon=True).start()
	log.info("gcal: sincronização ligada (agenda %s)", config.GCAL_ID)


def parar() -> None:
	_parar.set()
	_acordar.set()
