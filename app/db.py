"""Conexão com o SQLite e criação das tabelas."""
from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app import config

engine = None


def init_engine(url: str | None = None) -> None:
	"""Cria o engine (chamado na inicialização do app ou pelos testes)."""
	global engine
	if url is None:
		config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
		url = f"sqlite:///{config.DB_PATH}"
	kwargs = {"connect_args": {"check_same_thread": False}}
	if url == "sqlite://":  # memória (testes): uma conexão compartilhada
		from sqlalchemy.pool import StaticPool

		kwargs["poolclass"] = StaticPool
	engine = create_engine(url, **kwargs)

	@event.listens_for(engine, "connect")
	def _pragmas(conn, _):  # integridade referencial + escrita mais segura no cartão SD
		cur = conn.cursor()
		cur.execute("PRAGMA foreign_keys=ON")
		cur.execute("PRAGMA journal_mode=WAL")
		cur.close()


def create_db() -> None:
	from app import models  # noqa: F401  (registra as tabelas)

	SQLModel.metadata.create_all(engine)
	with Session(engine) as session:
		if not session.exec(select(models.Area)).first():
			for nome, cor in config.AREAS_PADRAO:
				session.add(models.Area(nome=nome, cor=cor))
			session.commit()


def get_session() -> Iterator[Session]:
	with Session(engine) as session:
		yield session
