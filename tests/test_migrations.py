"""The migrations must produce exactly the schema the models describe."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.config import _normalise_db_url
from app.db import MigrationError, alembic_config, migrate
from app.enums import ClaimType, HandoverStatus, Role, Sensitivity, SourceKind, Stance
from app.models import (AuditEvent, Base, Chunk, Claim, Evidence, Handover, HandoverRelease,
                        Project, Source, User, ClaimVersion)
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


# ------------------------------------------------------------ adopting a pre-migration database


def _legacy_with_data(eng):
    from sqlalchemy.orm import sessionmaker

    from app.models import Project
    Base.metadata.create_all(eng)
    with sessionmaker(eng)() as s:
        s.add(Project(name="Old project", outgoing_member="Riya"))
        s.commit()


def test_matching_legacy_schema_is_adopted_and_data_survives(eng):
    from app.db import adopt_legacy
    _legacy_with_data(eng)
    assert adopt_legacy(eng, dry_run=True) == ["mark the database as migration 0001"]
    assert "alembic_version" not in inspect(eng).get_table_names()     # dry run changed nothing
    adopt_legacy(eng)
    migrate(eng)                                                        # now starts normally
    with eng.connect() as c:
        assert c.execute(text("select name from projects")).scalar() == "Old project"


def test_legacy_database_missing_whole_tables_gets_them_created(eng):
    from app.db import adopt_legacy
    _legacy_with_data(eng)
    with eng.begin() as c:
        c.execute(text("DROP TABLE login_attempts"))
    done = adopt_legacy(eng)
    assert "create missing table login_attempts" in done
    migrate(eng)
    assert "login_attempts" in inspect(eng).get_table_names()
    with eng.connect() as c:
        assert c.execute(text("select count(*) from projects")).scalar() == 1


def test_legacy_database_with_a_different_column_is_refused_untouched(eng):
    from app.db import adopt_legacy
    _legacy_with_data(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE projects DROP COLUMN description"))
    with pytest.raises(MigrationError, match="cannot be fixed safely"):
        adopt_legacy(eng)
    assert "alembic_version" not in inspect(eng).get_table_names()
    with eng.connect() as c:
        assert c.execute(text("select name from projects")).scalar() == "Old project"


def test_adopt_refuses_empty_and_already_migrated_databases(eng):
    from app.db import adopt_legacy
    with pytest.raises(MigrationError, match="empty"):
        adopt_legacy(eng)
    migrate(eng)
    with pytest.raises(MigrationError, match="already has migration history"):
        adopt_legacy(eng)


def test_migration_enforces_append_only_audit_and_evidence_guards(eng):
    migrate(eng)
    Session = sessionmaker(eng, expire_on_commit=False)
    with Session() as session:
        project = Project(name="Audit migration test")
        reviewer = User(username="reviewer", display_name="Reviewer", role=Role.approver)
        session.add_all([project, reviewer])
        session.flush()

        source = Source(project_id=project.id, kind=SourceKind.notes, name="audit.md",
                        sensitivity=Sensitivity.team)
        chunk = Chunk(source=source, idx=0, text="Use Redis for the seat-lock service.",
                      sensitivity=Sensitivity.team)
        claim = Claim.create(
            project_id=project.id, statement="Use Redis for the seat-lock service.",
            type=ClaimType.decision, created_by="migration-test", sensitivity=Sensitivity.team,
        )
        claim.evidence.append(Evidence(
            chunk=chunk, snippet="Use Redis for the seat-lock service.", stance=Stance.supports,
        ))
        session.add_all([source, chunk, claim])
        session.flush()
        from app.verify import verify_claim
        verify_claim(claim)

        handover = Handover(
            project_id=project.id, title="Handover", outgoing_name="Riya",
            status=HandoverStatus.approved, approved_by_id=reviewer.id,
        )
        session.add(handover)
        session.flush()
        release = HandoverRelease(
            handover_id=handover.id, number=1, approved_by_id=reviewer.id,
            approved_by_name=reviewer.display_name, claims_json="[]",
        )
        session.add(release)
        session.commit()

        audit_id = session.scalar(select(AuditEvent.id).limit(1))
        version_id = session.scalar(select(ClaimVersion.id).limit(1))
        release_id, evidence_id = release.id, claim.evidence[0].id

        for statement, params in [
            ("UPDATE audit_events SET actor='tampered' WHERE id=:id", {"id": audit_id}),
            ("DELETE FROM claim_versions WHERE id=:id", {"id": version_id}),
            ("UPDATE handover_releases SET claims_json='[]' WHERE id=:id", {"id": release_id}),
            ("UPDATE evidence SET snippet='rewritten' WHERE id=:id", {"id": evidence_id}),
            ("DELETE FROM evidence WHERE id=:id", {"id": evidence_id}),
        ]:
            with pytest.raises(DBAPIError):
                session.execute(text(statement), params)
            session.rollback()

        # The one derived verification flag remains writable.
        session.execute(text("UPDATE evidence SET snippet_verified=1 WHERE id=:id"),
                        {"id": evidence_id})
        session.commit()
