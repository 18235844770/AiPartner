"""Track the next proactive review for each managed companion."""

from alembic import op
import sqlalchemy as sa


revision = "0021_companion_review"
down_revision = "0020_account_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companions", sa.Column("next_review_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_companions_managed_review", "companions", ["next_review_at"],
        postgresql_where=sa.text("initialization_status = 'ready'"),
    )


def downgrade() -> None:
    op.drop_index("ix_companions_managed_review", table_name="companions")
    op.drop_column("companions", "next_review_at")
