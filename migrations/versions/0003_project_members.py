"""project-scoped access: who may work in which project

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # A database adopted from an older build may already have this table (created from the models).
    if "project_members" in sa.inspect(bind).get_table_names():
        if bind.execute(sa.text("SELECT COUNT(*) FROM project_members")).scalar():
            return
        _backfill()
        return
    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("added_by", sa.String(length=128), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id"),
    )
    with op.batch_alter_table("project_members") as batch_op:
        batch_op.create_index("ix_project_members_project_id", ["project_id"])
        batch_op.create_index("ix_project_members_user_id", ["user_id"])
    _backfill()


def _backfill() -> None:
    # Keep today's behaviour for existing deployments: everyone who could reach the one
    # project keeps access to it.
    op.execute(
        "INSERT INTO project_members (project_id, user_id, added_by, added_at) "
        "SELECT p.id, u.id, 'migration', CURRENT_TIMESTAMP FROM projects p CROSS JOIN users u")


def downgrade() -> None:
    op.drop_table("project_members")
