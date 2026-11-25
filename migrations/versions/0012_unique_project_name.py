"""case-insensitive unique project names, so two admins cannot race past the name check

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_NAME = "uq_projects_name_lower"


def upgrade() -> None:
    bind = op.get_bind()
    dupes = bind.execute(sa.text(
        "SELECT lower(name) FROM projects GROUP BY lower(name) HAVING count(*) > 1")).fetchall()
    if dupes:
        # Never fail an upgrade over existing data; the app-level check still applies.
        return
    # IF NOT EXISTS, not an inspector check: SQLAlchemy does not reflect expression indexes on
    # SQLite, and a database adopted from the model may already have this index.
    op.execute(sa.text(f"CREATE UNIQUE INDEX IF NOT EXISTS {_NAME} ON projects (lower(name))"))


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {_NAME}"))
