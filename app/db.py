"""Conexão com o SQLite e criação das tabelas."""
from collections.abc import Iterator

from sqlalchemy import event, inspect
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
	_migrar_colunas()
	with Session(engine) as session:
		if not session.exec(select(models.Area)).first():
			for nome, cor in config.AREAS_PADRAO:
				session.add(models.Area(nome=nome, cor=cor))
			session.commit()


def _migrar_colunas() -> None:
	"""Migração simples: acrescenta colunas novas dos modelos em tabelas que já existem.

	O create_all só cria tabelas que faltam; isso cobre o caso comum de campo novo
	(sempre opcional ou com valor padrão). Renomear/remover coluna exige migração manual.
	"""
	from app import models

	tabelas = {m.__tablename__: m for m in (models.Area, models.Projeto, models.Item, models.Link, models.Ocorrencia)}
	with engine.begin() as conn:
		insp = inspect(conn)
		for nome, modelo in tabelas.items():
			existentes = {c["name"] for c in insp.get_columns(nome)}
			for col in modelo.__table__.columns:
				if col.name in existentes:
					continue
				tipo = col.type.compile(dialect=conn.dialect)
				padrao = modelo.model_fields[col.name].default
				padrao = getattr(padrao, "value", padrao)
				if padrao is None or not isinstance(padrao, (bool, int, float, str)):
					sql_padrao = ""
				elif isinstance(padrao, str):
					sql_padrao = " DEFAULT '" + padrao.replace("'", "''") + "'"
				else:
					sql_padrao = f" DEFAULT {int(padrao) if isinstance(padrao, bool) else padrao}"
				conn.exec_driver_sql(f'ALTER TABLE "{nome}" ADD COLUMN "{col.name}" {tipo}{sql_padrao}')
				print(f"[db] coluna nova: {nome}.{col.name}")
				if (nome, col.name) in AJUSTES_COLUNA_NOVA:
					conn.exec_driver_sql(AJUSTES_COLUNA_NOVA[(nome, col.name)])


# Valor inicial para dados que já existiam quando a coluna chegou
AJUSTES_COLUNA_NOVA = {
	# planos sequenciais (raiz) já criados: tarefas tratadas como dependentes
	("projeto", "tarefas_em_ordem"): "UPDATE projeto SET tarefas_em_ordem = 1 WHERE sequencial = 1 AND pai_id IS NULL",
}


def get_session() -> Iterator[Session]:
	with Session(engine) as session:
		yield session
