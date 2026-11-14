"""job worker columns: which worker holds a job and when it last reported

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("jobs")}
    with op.batch_alter_table("jobs") as batch:
        if "claimed_by" not in have:
            batch.add_column(sa.Column("claimed_by", sa.String(length=64), nullable=True))
        if "heartbeat_at" not in have:
            batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("heartbeat_at")
        batch.drop_column("claimed_by")
