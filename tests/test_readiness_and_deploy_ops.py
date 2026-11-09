"""Readiness endpoint, controlled migrations, rollback, and failure behaviour."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import app.db as dbmod
from app.config import Settings
from app.db import MigrationError, check_ready, downgrade, init_db, migrate, migration_state
from app.main import create_app
from tests.test_web import env  # noqa: F401


# ------------------------------------------------------------ readiness


def _app_on(app, engine):
    from sqlalchemy.orm import sessionmaker
    from app.db import get_session

    def dep():
        with sessionmaker(engine)() as s:
            yield s
    app.dependency_overrides[get_session] = dep


def test_ready_reports_ok_when_database_is_up_and_current(env, tmp_path):
    app, _ = env
    eng = create_engine(f"sqlite:///{tmp_path}/ok.db")
    migrate(eng)
    _app_on(app, eng)
    r = TestClient(app).get("/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


def test_ready_returns_503_without_leaking_details_when_database_is_down(env, tmp_path):
    app, _ = env
    _app_on(app, create_engine(f"sqlite:///{tmp_path}/missing-dir/nope.db"))
    r = TestClient(app).get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "database unreachable"}
    assert "sqlite" not in r.text and "missing-dir" not in r.text
    assert TestClient(app).get("/health").status_code == 200       # liveness is separate


def test_ready_is_503_while_migrations_are_pending(env, tmp_path):
    app, _ = env
    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    migrate(eng)
    downgrade("base", eng)
    assert check_ready(eng) == (False, "migrations behind")
    _app_on(app, eng)
    r = TestClient(app).get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "migrations behind"}


# ------------------------------------------------------------ controlled migrations


@pytest.fixture()
def eng(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path}/m.db")
    yield e
    e.dispose()


def test_migrate_on_startup_defaults_on_and_can_be_turned_off():
    assert Settings({}).migrate_on_startup is True
    assert Settings({"MIGRATE_ON_STARTUP": "false"}).migrate_on_startup is False


def test_startup_without_migrating_refuses_an_unmigrated_database(eng, monkeypatch):
    monkeypatch.setattr(dbmod, "engine", eng)
    with pytest.raises(MigrationError, match="python -m app.db upgrade"):
        init_db(upgrade=False)
    assert "alembic_version" not in inspect(eng).get_table_names()   # it changed nothing


def test_startup_without_migrating_accepts_a_database_migrated_beforehand(eng, monkeypatch):
    migrate(eng)
    monkeypatch.setattr(dbmod, "engine", eng)
    init_db(upgrade=False)
    assert migration_state(eng) == "current"


def test_upgrade_rollback_and_upgrade_again_keeps_the_schema_consistent(eng):
    assert migration_state(eng) == "unmigrated"
    migrate(eng)
    with eng.begin() as c:
        c.execute(text("INSERT INTO projects (name, description, outgoing_member, created_at) VALUES ('P', '', 'R', '2026-01-01')"))
    downgrade("base", eng)
    assert set(inspect(eng).get_table_names()) <= {"alembic_version"}
    assert migration_state(eng) == "behind"
    migrate(eng)
    assert migration_state(eng) == "current"
    with eng.connect() as c:                       # rolled back data is gone, as documented
        assert c.execute(text("select count(*) from projects")).scalar() == 0


def test_cli_status_and_downgrade_needs_confirmation(eng, monkeypatch, capsys):
    monkeypatch.setattr(dbmod, "engine", eng)
    migrate(eng)
    dbmod.main(["status"])
    assert capsys.readouterr().out.strip() == "current"
    with pytest.raises(SystemExit, match="--yes"):
        dbmod.main(["downgrade", "base"])
    assert migration_state(eng) == "current"
    dbmod.main(["downgrade", "base", "--yes"])
    assert migration_state(eng) == "behind"
