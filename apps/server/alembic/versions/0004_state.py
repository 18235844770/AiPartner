"""State 当前快照与变化事件。source_type 使用 VARCHAR(32)，因为 dialogue_decision 超过设计稿的 16。决策表尚未建立，dialogue_decision_id 暂不建外键。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_state"
down_revision: str | None = "0003_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = (
    "emotion_changed",
    "relationship_changed",
    "interaction_changed",
    "motivation_changed",
    "multiple_changed",
    "state_initialized",
    "state_recovered",
)
_SOURCE_TYPES = (
    "user_message",
    "companion_action",
    "dialogue_decision",
    "background_task",
    "system",
)


def upgrade() -> None:
    op.create_table(
        "companion_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("emotion", postgresql.JSONB(), nullable=False),
        sa.Column("relationship", postgresql.JSONB(), nullable=False),
        sa.Column("interaction", postgresql.JSONB(), nullable=False),
        sa.Column("motivation", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_companion_states_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companion_states"),
        sa.UniqueConstraint("companion_id", name="uq_companion_states_companion_id"),
        sa.CheckConstraint("version >= 1", name="ck_companion_states_version_positive"),
    )
    event_type_sql = "event_type IN (" + ", ".join(f"'{item}'" for item in _EVENT_TYPES) + ")"
    source_type_sql = "source_type IN (" + ", ".join(f"'{item}'" for item in _SOURCE_TYPES) + ")"
    op.create_table(
        "state_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dialogue_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_before", sa.Integer(), nullable=True),
        sa.Column("version_after", sa.Integer(), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_state_events_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_state_events_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_state_events_message_id_messages",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_state_events"),
        sa.CheckConstraint(event_type_sql, name="ck_state_events_event_type"),
        sa.CheckConstraint(source_type_sql, name="ck_state_events_source_type"),
        sa.CheckConstraint("char_length(reason) > 0", name="ck_state_events_reason_nonempty"),
        sa.CheckConstraint(
            "version_before IS NULL OR version_before >= 1",
            name="ck_state_events_version_before_positive",
        ),
        sa.CheckConstraint(
            "version_after IS NULL OR version_after >= 1",
            name="ck_state_events_version_after_positive",
        ),
        sa.CheckConstraint(
            "version_before IS NULL OR version_after IS NULL OR version_after > version_before",
            name="ck_state_events_version_moves_forward",
        ),
    )
    op.create_index(
        "uq_state_event_version",
        "state_events",
        ["companion_id", "version_after"],
        unique=True,
        postgresql_where=sa.text("version_after IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_state_event_version", table_name="state_events")
    op.drop_table("state_events")
    op.drop_table("companion_states")
