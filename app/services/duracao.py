"""Duração em texto <-> minutos (formulário e planejamento usam a mesma regra)."""
import re


def ler(texto: str | None) -> int | None:
	"""'1h', '1h30', '1:30', '90', '90min', '1,5h' -> minutos. Vazio -> None."""
	t = (texto or "").strip().lower().replace(" ", "").replace(",", ".")
	if not t:
		return None
	if m := re.fullmatch(r"(\d+(?:\.\d+)?)h(?:(\d+)(?:m|min)?)?", t):
		total = round(float(m.group(1)) * 60) + int(m.group(2) or 0)
	elif m := re.fullmatch(r"(\d+):(\d{1,2})", t):
		total = int(m.group(1)) * 60 + int(m.group(2))
	elif m := re.fullmatch(r"(\d+)(?:m|min)?", t):
		total = int(m.group(1))
	else:
		raise ValueError(f"duração inválida: {texto!r} (use 1h, 1h30, 45min…)")
	if total < 1:
		raise ValueError("duração precisa ser de pelo menos 1 minuto")
	return total


def texto(minutos: int | None) -> str:
	"""90 -> '1h30' ; 60 -> '1h' ; 45 -> '45min'"""
	if not minutos:
		return ""
	h, m = divmod(int(minutos), 60)
	if not h:
		return f"{m}min"
	return f"{h}h{m:02d}" if m else f"{h}h"
