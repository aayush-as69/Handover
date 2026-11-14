"""normalize release claims: one row per claim in a release

Revision ID: 0010
Revises: 0009

Adds handover_release_claims, backfills it from handover_releases.claims_json and makes it
append-only like the release. claims_json stays (releases are immutable, so it cannot be
cleared); new releases write both.
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TABLE = "handover_release_claims"


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["handover_releases.id"]),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", "claim_id"))
    op.create_index(f"ix_{TABLE}_release_id", TABLE, ["release_id"])
    op.create_index(f"ix_{TABLE}_claim_id", TABLE, ["claim_id"])

    releases = bind.execute(sa.text("SELECT id, claims_json FROM handover_releases")).all()
    rows = []
    for rid, raw in releases:
        seen = set()
        for pos, pair in enumerate(json.loads(raw or "[]")):
            claim_id, version = int(pair[0]), int(pair[1])
            if claim_id in seen:
                continue
            seen.add(claim_id)
            rows.append({"release_id": rid, "claim_id": claim_id, "version": version, "position": pos})
    if rows:
        bind.execute(sa.text(f"INSERT INTO {TABLE} (release_id, claim_id, version, position) "
                             "VALUES (:release_id, :claim_id, :version, :position)"), rows)

    if bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER immutable_{TABLE}_{action.lower()} BEFORE {action} ON {TABLE} "
                       "BEGIN SELECT RAISE(ABORT, 'append-only record'); END")
    elif bind.dialect.name == "postgresql":
        op.execute(f"CREATE TRIGGER immutable_{TABLE} BEFORE UPDATE OR DELETE ON {TABLE} "
                   "FOR EACH ROW EXECUTE FUNCTION handover_reject_immutable_mutation()")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS immutable_{TABLE}_{action}")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{TABLE} ON {TABLE}")
    op.drop_table(TABLE)
