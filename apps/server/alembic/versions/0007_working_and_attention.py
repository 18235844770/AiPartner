"""会话工作记忆与长期关注主题。工作记忆不进入 memories 的生命周期。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_working_and_attention"
down_revision: str | None = "0006_infrastructure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_conversations_companion_id", "conversations", ["companion_id", "id"])
    op.create_unique_constraint("uq_memories_companion_id", "memories", ["companion_id", "id"])
    op.create_table(
        "attention_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("origin_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("interest_score", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")),
        sa.Column("last_discussed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_attention_topics_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attention_topics"),
        sa.UniqueConstraint("companion_id", "id", name="uq_attention_topics_companion_id"),
        sa.CheckConstraint(
            "origin_type IN ('user_related', 'persona_autonomous')",
            name="ck_attention_topics_origin_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name="ck_attention_topics_status",
        ),
        sa.CheckConstraint("char_length(title) > 0", name="ck_attention_topics_title_nonempty"),
        sa.CheckConstraint(
            "interest_score BETWEEN 0 AND 1",
            name="ck_attention_topics_interest_score_range",
        ),
    )
    op.create_index(
        "ix_attention_topics_companion_status",
        "attention_topics",
        ["companion_id", "status"],
    )
    op.create_index(
        "ix_attention_topics_status_review",
        "attention_topics",
        ["status", "next_review_at"],
    )
    op.create_table(
        "working_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("current_topic", sa.String(128), nullable=True),
        sa.Column("attention_topic_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("open_threads", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["companion_id", "conversation_id"],
            ["conversations.companion_id", "conversations.id"],
            name="fk_working_memories_conversation_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["companion_id", "attention_topic_id"],
            ["attention_topics.companion_id", "attention_topics.id"],
            name="fk_working_memories_attention_topic_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_working_memories"),
        sa.UniqueConstraint("conversation_id", name="uq_working_memories_conversation_id"),
        sa.CheckConstraint("version >= 1", name="ck_working_memories_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(open_threads) = 'array'",
            name="ck_working_memories_open_threads_array",
        ),
    )
    op.create_index("ix_working_memories_companion_id", "working_memories", ["companion_id"])
    op.create_table(
        "attention_topic_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["companion_id", "topic_id"],
            ["attention_topics.companion_id", "attention_topics.id"],
            name="fk_attention_topic_memories_topic_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["companion_id", "memory_id"],
            ["memories.companion_id", "memories.id"],
            name="fk_attention_topic_memories_memory_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attention_topic_memories"),
        sa.UniqueConstraint("topic_id", "memory_id", name="uq_attention_topic_memories_topic_memory"),
    )


def downgrade() -> None:
    op.drop_table("attention_topic_memories")
    op.drop_index("ix_working_memories_companion_id", table_name="working_memories")
    op.drop_table("working_memories")
    op.drop_index("ix_attention_topics_status_review", table_name="attention_topics")
    op.drop_index("ix_attention_topics_companion_status", table_name="attention_topics")
    op.drop_table("attention_topics")
    op.drop_constraint("uq_memories_companion_id", "memories", type_="unique")
    op.drop_constraint("uq_conversations_companion_id", "conversations", type_="unique")
