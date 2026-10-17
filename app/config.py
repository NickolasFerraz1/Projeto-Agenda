"""Configurações do app (variáveis de ambiente com valores padrão)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _carregar_env(arquivo: Path) -> None:
	"""Lê um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
	if not arquivo.exists():
		return
	for linha in arquivo.read_text(encoding="utf-8").splitlines():
		linha = linha.strip()
		if not linha or linha.startswith("#") or "=" not in linha:
			continue
		chave, valor = linha.split("=", 1)
		os.environ.setdefault(chave.strip(), valor.strip().strip("\"'"))


_carregar_env(ROOT / ".env")  # fora do Git (ver .env.example)

# Banco SQLite. Em testes, usa-se um banco em memória (ver tests/conftest.py).
DB_PATH = Path(os.environ.get("AGENDA_DB", ROOT / "data" / "agenda.db"))

# Datas e horários são guardados no horário local (sem fuso), que é o do Pi e do usuário.
TIMEZONE = os.environ.get("AGENDA_TZ", "America/Sao_Paulo")

# Versão dos arquivos estáticos: trocar ao mudar CSS/JS/ícones (renova o cache do PWA).
ASSET_VERSION = "7"

# Áreas criadas no primeiro uso (editáveis depois).
AREAS_PADRAO = [
	("Estudo", "#6cc8ff"),
	("Trabalho", "#ffc861"),
	("Pessoal", "#6fe39a"),
	("Lazer", "#b3a1ff"),
]

# ---------- Google Agenda (opcional) ----------
# Sem AGENDA_GCAL_ID, a sincronização fica desligada.
GCAL_ID = os.environ.get("AGENDA_GCAL_ID", "").strip()
GCAL_CRED = Path(os.environ.get("AGENDA_GCAL_CRED", ROOT / "data" / "google-credenciais.json"))
GCAL_INTERVALO = int(os.environ.get("AGENDA_GCAL_INTERVALO", 15 * 60))  # conferência periódica (s)
# Endereço do app, para o link "abrir no app" na descrição dos eventos
URL_APP = os.environ.get("AGENDA_URL", "http://localhost:8090").rstrip("/")
