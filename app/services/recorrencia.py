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
