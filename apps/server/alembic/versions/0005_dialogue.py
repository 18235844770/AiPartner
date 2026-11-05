"""Dialogue 决策记录。主要行为采用产品方案的七种基础行为。Quiet 不产生结果消息。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_dialogue"
down_revision: str | None = "0004_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIGGER_TYPES = ("user_message", "proactive", "system_event", "background")
_ACTIONS = ("respond", "share", "ask", "react", "continue", "close", "quiet")
_STATUSES = ("pending", "approved", "executing", "completed", "rejected", "failed", "cancelled")


def upgrade() -> None:
    op.create_table(
        "dialogue_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_type", sa.String(16), nullable=False),
        sa.Column("primary_action", sa.String(32), nullable=False),
        sa.Column("secondary_actions", postgresql.JSONB(), nullable=False),
        sa.Column("motivation", postgresql.JSONB(), nullable=False),
        sa.Column("topic", postgresql.JSONB(), nullable=False),
        sa.Column("model_proposal", postgresql.JSONB(), nullable=False),
        sa.Column("validation_result", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_dialogue_decisions_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_dialogue_decisions_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_message_id"],
            ["messages.id"],
            name="fk_dialogue_decisions_trigger_message_id_messages",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_message_id"],
            ["messages.id"],
            name="fk_dialogue_decisions_result_message_id_messages",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dialogue_decisions"),
        sa.CheckConstraint(
            "trigger_type IN (" + ", ".join(f"'{item}'" for item in _TRIGGER_TYPES) + ")",
            name="ck_dialogue_decisions_trigger_type",
        ),
        sa.CheckConstraint(
            "primary_action IN (" + ", ".join(f"'{item}'" for item in _ACTIONS) + ")",
            name="ck_dialogue_decisions_primary_action",
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{item}'" for item in _STATUSES) + ")",
            name="ck_dialogue_decisions_status",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_dialogue_decisions_confidence_range"),
        sa.CheckConstraint(
            "char_length(reasoning_summary) > 0",
            name="ck_dialogue_decisions_reasoning_nonempty",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR (status <> 'completed' AND completed_at IS NULL)",
            name="ck_dialogue_decisions_completed_consistency",
        ),
        sa.CheckConstraint(
            "primary_action <> 'quiet' OR (status = 'completed' AND result_message_id IS NULL)",
            name="ck_dialogue_decisions_quiet_has_no_message",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR primary_action = 'quiet' OR result_message_id IS NOT NULL",
            name="ck_dialogue_decisions_completed_message_required",
        ),
    )
    op.create_index(
        "ix_dialogue_decisions_companion_created",
        "dialogue_decisions",
        ["companion_id", "created_at"],
    )
    op.create_index(
        "ix_dialogue_decisions_conversation_created",
        "dialogue_decisions",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_dialogue_decisions_status_created",
        "dialogue_decisions",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_dialogue_decisions_trigger_message",
        "dialogue_decisions",
        ["trigger_message_id"],
    )
    op.create_index(
        "uq_dialogue_decisions_result_message",
        "dialogue_decisions",
        ["result_message_id"],
        unique=True,
        postgresql_where=sa.text("result_message_id IS NOT NULL"),
    )
    op.create_foreign_key(
        "fk_state_events_dialogue_decision_id_dialogue_decisions",
        "state_events",
        "dialogue_decisions",
        ["dialogue_decision_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_state_events_dialogue_decision_id_dialogue_decisions",
        "state_events",
        type_="foreignkey",
    )
    op.drop_index("uq_dialogue_decisions_result_message", table_name="dialogue_decisions")
    op.drop_index("ix_dialogue_decisions_trigger_message", table_name="dialogue_decisions")
    op.drop_index("ix_dialogue_decisions_status_created", table_name="dialogue_decisions")
    op.drop_index("ix_dialogue_decisions_conversation_created", table_name="dialogue_decisions")
    op.drop_index("ix_dialogue_decisions_companion_created", table_name="dialogue_decisions")
    op.drop_table("dialogue_decisions")
