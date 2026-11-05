import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.dialogue.domain.enums import DecisionStatus, DialogueAction, TriggerType
from app.shared.database.base import Base
from app.shared.database.mixins import UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID


def _in_list(column: str, values: type) -> str:
    quoted = ", ".join(f"'{item.value}'" for item in values)
    return f"{column} IN ({quoted})"


class DialogueDecision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "dialogue_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_dialogue_decisions_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_dialogue_decisions_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["trigger_message_id"],
            ["messages.id"],
            name="fk_dialogue_decisions_trigger_message_id_messages",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["result_message_id"],
            ["messages.id"],
            name="fk_dialogue_decisions_result_message_id_messages",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("trigger_type", TriggerType), name="trigger_type"),
        CheckConstraint(_in_list("primary_action", DialogueAction), name="primary_action"),
        CheckConstraint(_in_list("status", DecisionStatus), name="status"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("char_length(reasoning_summary) > 0", name="reasoning_nonempty"),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR (status <> 'completed' AND completed_at IS NULL)",
            name="completed_consistency",
        ),
        CheckConstraint(
            "primary_action <> 'quiet' OR (status = 'completed' AND result_message_id IS NULL)",
            name="quiet_has_no_message",
        ),
        CheckConstraint(
            "status <> 'completed' OR primary_action = 'quiet' OR result_message_id IS NOT NULL",
            name="completed_message_required",
        ),
        Index("ix_dialogue_decisions_companion_created", "companion_id", "created_at"),
        Index("ix_dialogue_decisions_conversation_created", "conversation_id", "created_at"),
        Index("ix_dialogue_decisions_status_created", "status", "created_at"),
        Index("ix_dialogue_decisions_trigger_message", "trigger_message_id"),
        Index(
            "uq_dialogue_decisions_result_message",
            "result_message_id",
            unique=True,
            postgresql_where=text("result_message_id IS NOT NULL"),
        ),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trigger_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    result_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    primary_action: Mapped[str] = mapped_column(String(32), nullable=False)
    secondary_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    motivation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    topic: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    model_proposal: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    validation_result: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
