"""Configurações do app (variáveis de ambiente com valores padrão)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Banco SQLite. Em testes, usa-se um banco em memória (ver tests/conftest.py).
DB_PATH = Path(os.environ.get("AGENDA_DB", ROOT / "data" / "agenda.db"))

# Datas e horários são guardados no horário local (sem fuso), que é o do Pi e do usuário.
TIMEZONE = os.environ.get("AGENDA_TZ", "America/Sao_Paulo")

# Versão dos arquivos estáticos: trocar ao mudar CSS/JS/ícones (renova o cache do PWA).
ASSET_VERSION = "5"

# Áreas criadas no primeiro uso (editáveis depois).
AREAS_PADRAO = [
	("Estudo", "#6cc8ff"),
	("Trabalho", "#ffc861"),
	("Pessoal", "#6fe39a"),
	("Lazer", "#b3a1ff"),
]
