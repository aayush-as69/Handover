"""The migrations must produce exactly the schema the models describe."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.config import _normalise_db_url
from app.db import MigrationError, alembic_config, migrate
from app.models import Base
from tests.dbutil import PG_URL, on_postgres


def fresh_engine(tmp_path):
    if on_postgres():
        eng = create_engine(_normalise_db_url(PG_URL))
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
        return eng
    return create_engine(f"sqlite:///{tmp_path / 'm.db'}")


@pytest.fixture()
def eng(tmp_path):
    e = fresh_engine(tmp_path)
    yield e
    e.dispose()
    if on_postgres():          # leave the shared test schema usable for the next tests
        Base.metadata.create_all(create_engine(_normalise_db_url(PG_URL)))


def test_upgrade_creates_exactly_the_model_schema(eng):
    migrate(eng)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}),
                                Base.metadata)
    assert diff == []


def test_upgrade_is_repeatable(eng):
    migrate(eng)
    migrate(eng)
    assert "claims" in inspect(eng).get_table_names()


def test_downgrade_removes_everything(eng):
    migrate(eng)
    with eng.begin() as conn:
        command.downgrade(alembic_config(conn), "base")
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}


def test_a_database_without_migration_history_is_refused(eng):
    Base.metadata.create_all(eng)
    with pytest.raises(MigrationError, match="before migrations existed"):
        migrate(eng)


def test_the_important_indexes_exist(eng):
    migrate(eng)
    idx = {(t, tuple(i["column_names"])) for t in ("claims", "evidence", "chunks", "audit_events")
           for i in inspect(eng).get_indexes(t)}
    assert ("claims", ("project_id",)) in idx and ("claims", ("review_status",)) in idx
    assert ("evidence", ("claim_id",)) in idx and ("chunks", ("source_id",)) in idx
