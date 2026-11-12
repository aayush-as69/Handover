"""per-project roles

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("project_members")}
    if "role" in cols:
        return
    # NULL keeps today's behaviour: the person's default role applies in every project.
    with op.batch_alter_table("project_members") as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("project_members") as batch_op:
        batch_op.drop_column("role")
