"""claim comments

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "claim_comments" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "claim_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_claim_comments_claim_id", "claim_comments", ["claim_id"])


def downgrade() -> None:
    op.drop_table("claim_comments")
