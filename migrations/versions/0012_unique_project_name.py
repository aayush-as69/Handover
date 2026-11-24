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
    insp = sa.inspect(bind)
    if _NAME in {i["name"] for i in insp.get_indexes("projects")}:
        return
    dupes = bind.execute(sa.text(
        "SELECT lower(name) FROM projects GROUP BY lower(name) HAVING count(*) > 1")).fetchall()
    if dupes:
        # Never fail an upgrade over existing data; the app-level check still applies.
        return
    op.create_index(_NAME, "projects", [sa.text("lower(name)")], unique=True)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _NAME in {i["name"] for i in insp.get_indexes("projects")}:
        op.drop_index(_NAME, table_name="projects")
