"""One place that decides which database the tests run on.

Default: a fresh in-memory SQLite per test. With TEST_DATABASE_URL set to a PostgreSQL URL the
same tests run against a real PostgreSQL (tables are emptied between tests), which is how the
race, constraint and migration behaviour gets proven on the production database.
"""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.config import _normalise_db_url
from app.models import Base

PG_URL = os.environ.get("TEST_DATABASE_URL")
_pg_engine = None


def on_postgres() -> bool:
    return bool(PG_URL)


def new_engine():
    global _pg_engine
    if not PG_URL:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                            poolclass=StaticPool)
        Base.metadata.create_all(eng)
        return eng
    if _pg_engine is None:
        _pg_engine = create_engine(_normalise_db_url(PG_URL), pool_pre_ping=True)
        Base.metadata.drop_all(_pg_engine)
        Base.metadata.create_all(_pg_engine)
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with _pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    return _pg_engine
