"""server-side sessions so sign-out revokes a cookie, plus indexes on four user foreign keys

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_INDEXES = [
    ("ix_handovers_incoming_user_id", "handovers", "incoming_user_id"),
    ("ix_handovers_approved_by_id", "handovers", "approved_by_id"),
    ("ix_handover_releases_approved_by_id", "handover_releases", "approved_by_id"),
    ("ix_acknowledgements_user_id", "acknowledgements", "user_id"),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "user_sessions" not in insp.get_table_names():
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
        op.create_index("ix_user_sessions_created_at", "user_sessions", ["created_at"])
    for name, table, column in _INDEXES:
        have = {i["name"] for i in insp.get_indexes(table)} if table in insp.get_table_names() else None
        if have is not None and name not in have:
            op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in _INDEXES:
        op.drop_index(name, table_name=table)
    op.drop_table("user_sessions")
