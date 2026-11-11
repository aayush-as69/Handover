"""Session revocation and database-enforced append-only records.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APPEND_ONLY_TABLES = ("claim_versions", "audit_events", "handover_releases")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), server_default="1", nullable=False),
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER immutable_{table}_{action.lower()} "
                    f"BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'append-only record'); END"
                )
        op.execute(
            "CREATE TRIGGER evidence_identity_guard_update "
            "BEFORE UPDATE OF claim_id, chunk_id, snippet, stance ON evidence "
            "BEGIN SELECT RAISE(ABORT, 'stored evidence is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER evidence_identity_guard_delete "
            "BEFORE DELETE ON evidence "
            "BEGIN SELECT RAISE(ABORT, 'stored evidence is immutable'); END"
        )
    elif dialect == "postgresql":
        op.execute("""
            CREATE FUNCTION handover_reject_immutable_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION '% records are append-only', TG_TABLE_NAME;
            END;
            $$
        """)
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"CREATE TRIGGER immutable_{table} "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION handover_reject_immutable_mutation()"
            )
        op.execute("""
            CREATE FUNCTION handover_guard_evidence_update()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.claim_id IS DISTINCT FROM OLD.claim_id
                   OR NEW.chunk_id IS DISTINCT FROM OLD.chunk_id
                   OR NEW.snippet IS DISTINCT FROM OLD.snippet
                   OR NEW.stance IS DISTINCT FROM OLD.stance THEN
                    RAISE EXCEPTION 'stored evidence is immutable';
                END IF;
                RETURN NEW;
            END;
            $$
        """)
        op.execute("""
            CREATE TRIGGER evidence_identity_guard_update
            BEFORE UPDATE ON evidence
            FOR EACH ROW EXECUTE FUNCTION handover_guard_evidence_update()
        """)
        op.execute("""
            CREATE TRIGGER evidence_identity_guard_delete
            BEFORE DELETE ON evidence
            FOR EACH ROW EXECUTE FUNCTION handover_reject_immutable_mutation()
        """)
    else:
        raise RuntimeError(f"Unsupported database dialect for audit guards: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"DROP TRIGGER IF EXISTS immutable_{table}_{action.lower()}")
        op.execute("DROP TRIGGER IF EXISTS evidence_identity_guard_update")
        op.execute("DROP TRIGGER IF EXISTS evidence_identity_guard_delete")
    elif dialect == "postgresql":
        for table in APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS immutable_{table} ON {table}")
        op.execute("DROP TRIGGER IF EXISTS evidence_identity_guard_update ON evidence")
        op.execute("DROP TRIGGER IF EXISTS evidence_identity_guard_delete ON evidence")
        op.execute("DROP FUNCTION IF EXISTS handover_guard_evidence_update()")
        op.execute("DROP FUNCTION IF EXISTS handover_reject_immutable_mutation()")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("session_version")
