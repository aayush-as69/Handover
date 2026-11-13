"""link claim comments to their author's account

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "user_id" in {c["name"] for c in insp.get_columns("claim_comments")}:
        return
    with op.batch_alter_table("claim_comments") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_claim_comments_user_id", "users", ["user_id"], ["id"])
        batch.create_index("ix_claim_comments_user_id", ["user_id"])
    # Link old comments only where the saved name matches exactly one account.
    bind.execute(sa.text(
        "UPDATE claim_comments SET user_id = (SELECT MIN(u.id) FROM users u "
        "WHERE u.display_name = claim_comments.author) "
        "WHERE (SELECT COUNT(*) FROM users u WHERE u.display_name = claim_comments.author) = 1"))


def downgrade() -> None:
    with op.batch_alter_table("claim_comments") as batch:
        batch.drop_index("ix_claim_comments_user_id")
        batch.drop_constraint("fk_claim_comments_user_id", type_="foreignkey")
        batch.drop_column("user_id")
