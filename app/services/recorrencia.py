"""Recorrência no padrão iCalendar (RRULE), o mesmo que o Google Agenda usa."""
from datetime import date, datetime, time, timedelta

from dateutil.rrule import rrulestr


def validar(regra: str) -> str:
	"""Normaliza e valida uma RRULE; levanta ValueError se for inválida."""
	regra = regra.strip().removeprefix("RRULE:")
	rrulestr(regra, dtstart=datetime(2000, 1, 1))  # só para validar
	return regra


def ocorrencias(regra: str, dtstart: datetime, de: date, ate: date) -> list[datetime]:
	"""Datas/horas em que o item acontece entre `de` e `ate` (inclusive)."""
	regra_obj = rrulestr(regra, dtstart=dtstart)
	inicio = datetime.combine(de, time.min)
	fim = datetime.combine(ate, time.max)
	return list(regra_obj.between(inicio, fim, inc=True))


def duracao(inicio: datetime | None, fim: datetime | None) -> timedelta | None:
	if inicio and fim:
		return fim - inicio
	return None


# ---------- Formulário (interface web) ----------
# A interface oferece presets; a regra gravada continua sendo uma RRULE comum.
DIAS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DIAS_NOME = {"MO": "seg", "TU": "ter", "WE": "qua", "TH": "qui", "FR": "sex", "SA": "sáb", "SU": "dom"}
UTEIS = ["MO", "TU", "WE", "TH", "FR"]


def montar_regra(freq: str, dias: list[str] | None = None, ate: date | None = None, custom: str = "") -> str | None:
	"""Converte os campos do formulário numa RRULE (ou None = não repete)."""
	dias = [d for d in DIAS if d in (dias or [])]  # ordem canônica, sem lixo
	if freq == "custom":
		return validar(custom) if custom.strip() else None
	if freq == "DAILY":
		partes = ["FREQ=DAILY"]
	elif freq == "WEEKDAYS":
		partes = ["FREQ=WEEKLY", "BYDAY=" + ",".join(UTEIS)]
	elif freq == "WEEKLY":
		partes = ["FREQ=WEEKLY"] + (["BYDAY=" + ",".join(dias)] if dias else [])
	elif freq == "MONTHLY":
		partes = ["FREQ=MONTHLY"]
	else:
		return None
	if ate:
		partes.append(f"UNTIL={ate:%Y%m%d}T235959")
	return ";".join(partes)


def ler_regra(regra: str | None) -> dict:
	"""Inverso de montar_regra: preenche o formulário a partir de uma RRULE."""
	vazio = {"freq": "", "dias": [], "ate": None, "custom": ""}
	if not regra:
		return vazio
	campos = dict(p.split("=", 1) for p in regra.split(";") if "=" in p)
	ate = None
	if "UNTIL" in campos:
		try:
			ate = datetime.strptime(campos["UNTIL"][:8], "%Y%m%d").date()
		except ValueError:
			return {**vazio, "freq": "custom", "custom": regra}
	extras = set(campos) - {"FREQ", "BYDAY", "UNTIL"}
	freq, byday = campos.get("FREQ"), campos.get("BYDAY", "")
	dias = byday.split(",") if byday else []
	if extras or any(d not in DIAS for d in dias):
		return {**vazio, "freq": "custom", "custom": regra}
	if freq == "DAILY" and not dias:
		return {**vazio, "freq": "DAILY", "ate": ate}
	if freq == "WEEKLY" and dias == UTEIS:
		return {**vazio, "freq": "WEEKDAYS", "ate": ate}
	if freq == "WEEKLY":
		return {**vazio, "freq": "WEEKLY", "dias": dias, "ate": ate}
	if freq == "MONTHLY" and not dias:
		return {**vazio, "freq": "MONTHLY", "ate": ate}
	return {**vazio, "freq": "custom", "custom": regra}


def descrever(regra: str | None) -> str:
	"""Texto curto em português: "toda ter e qui", "dias úteis até 12/12"…"""
	if not regra:
		return ""
	f = ler_regra(regra)
	texto = {
		"DAILY": "todo dia",
		"WEEKDAYS": "dias úteis",
		"MONTHLY": "todo mês",
		"WEEKLY": "toda " + " e ".join(", ".join(DIAS_NOME[d] for d in f["dias"]).rsplit(", ", 1)) if f["dias"] else "toda semana",
	}.get(f["freq"], "personalizada")
	if f["ate"]:
		texto += f" até {f['ate']:%d/%m/%Y}"
	return texto
