"""teams and onboarding progress

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "teams" not in have:
        op.create_table(
            "teams",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("created_by", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("name"))
    if "team_members" not in have:
        op.create_table(
            "team_members",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("team_id", "user_id"))
        op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
        op.create_index("ix_team_members_user_id", "team_members", ["user_id"])
    if "onboarding_steps" not in have:
        op.create_table(
            "onboarding_steps",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("release_number", sa.Integer(), nullable=False),
            sa.Column("step_key", sa.String(length=32), nullable=False),
            sa.Column("done_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "project_id", "release_number", "step_key"))
        op.create_index("ix_onboarding_steps_user_id", "onboarding_steps", ["user_id"])
        op.create_index("ix_onboarding_steps_project_id", "onboarding_steps", ["project_id"])


def downgrade() -> None:
    op.drop_table("onboarding_steps")
    op.drop_table("team_members")
    op.drop_table("teams")
