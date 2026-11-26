"""Add durable accepted chat turns before dialogue decisions are created."""

from alembic import op
import sqlalchemy as sa


revision = "0020_account_chat"
down_revision = "0019_account_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_sequence", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["conversation_id", "trigger_sequence"], ["messages.conversation_id", "messages.sequence_number"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("conversation_id", "trigger_sequence"),
        sa.CheckConstraint("status IN ('pending', 'running', 'replied', 'quiet', 'failed')", name="status"),
    )
    op.create_index("ix_chat_turns_status_created", "chat_turns", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("chat_turns")
