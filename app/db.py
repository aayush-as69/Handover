from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from .config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

ROOT = Path(__file__).resolve().parents[1]


class MigrationError(RuntimeError):
    pass


def alembic_config(connection) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def migrate(eng=None) -> None:
    """Bring the database to the latest schema. Safe to run on every start.

    A database that has tables but no migration history was made by an older build that
    created tables directly. It cannot be upgraded safely, so we stop with instructions
    instead of guessing.
    """
    eng = eng or engine
    with eng.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        if tables and "alembic_version" not in tables:
            raise MigrationError(
                "This database was created before migrations existed. Use a new database "
                "(for the demo, delete handover.db) or ask for a one-off upgrade.")
        command.upgrade(alembic_config(conn), "head")


def init_db() -> None:
    migrate()


def get_session():
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
