"""Backup do SQLite (seguro com o app rodando: usa a API de backup do sqlite3).

Gera data/backups/agenda-AAAA-MM-DD.db e mantém os últimos 14.
Uso: python scripts/backup.py   (o timer do systemd roda todo dia às 03:30)
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import config  # noqa: E402

MANTER = 14


def main() -> None:
	origem = config.DB_PATH
	if not origem.exists():
		print(f"banco não encontrado: {origem}")
		return
	pasta = origem.parent / "backups"
	pasta.mkdir(parents=True, exist_ok=True)
	destino = pasta / f"agenda-{date.today():%Y-%m-%d}.db"
	with sqlite3.connect(origem) as src, sqlite3.connect(destino) as dst:
		src.backup(dst)
	antigos = sorted(pasta.glob("agenda-*.db"))[:-MANTER]
	for f in antigos:
		f.unlink()
	print(f"backup: {destino} ({destino.stat().st_size // 1024} KB); removidos {len(antigos)} antigos")


if __name__ == "__main__":
	main()
