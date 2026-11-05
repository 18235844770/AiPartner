"""Identity 与 Conversation 初始结构，并启用 pgvector。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity_conversation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("locale", sa.String(16), nullable=False, server_default=sa.text("'zh-CN'")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status = 'active'", name="ck_users_status"),
        sa.CheckConstraint("char_length(display_name) > 0", name="ck_users_display_name_nonempty"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "companions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_companions_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("owner_user_id", "id", name="uq_companions_owner_user_id_id"),
        sa.CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_companions_status"),
        sa.CheckConstraint("char_length(name) > 0", name="ck_companions_name_nonempty"),
        sa.CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR (status <> 'archived' AND archived_at IS NULL)",
            name="ck_companions_archive_consistency",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companions"),
    )
    op.create_index(
        "uq_companion_default",
        "companions",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND status = 'active'"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("next_sequence_number", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "companion_id"],
            ["companions.owner_user_id", "companions.id"],
            name="fk_conversations_user_companion",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "companion_id", "id", name="uq_conversations_user_companion_id"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_conversations_status"),
        sa.CheckConstraint("next_sequence_number >= 1", name="ck_conversations_next_sequence_number_positive"),
        sa.CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR (status <> 'archived' AND archived_at IS NULL)",
            name="ck_conversations_archive_consistency",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("client_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False, server_default=sa.text("'text'")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'recorded'")),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("conversation_id", "sequence_number", name="uq_messages_conversation_sequence"),
        sa.CheckConstraint("sender_type IN ('user', 'companion', 'system')", name="ck_messages_sender_type"),
        sa.CheckConstraint("content_type = 'text'", name="ck_messages_content_type"),
        sa.CheckConstraint("char_length(content) > 0", name="ck_messages_content_nonempty"),
        sa.CheckConstraint("char_length(status) > 0", name="ck_messages_status_nonempty"),
        sa.CheckConstraint("sequence_number >= 1", name="ck_messages_sequence_number_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index(
        "uq_message_client_id",
        "messages",
        ["conversation_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_message_client_id", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_index("uq_companion_default", table_name="companions")
    op.drop_table("companions")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
