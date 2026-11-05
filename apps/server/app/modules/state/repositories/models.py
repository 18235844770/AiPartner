import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.state.domain.enums import StateEventType, StateSourceType
from app.shared.database.base import Base
from app.shared.database.mixins import UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID


def _in_list(column: str, values: type) -> str:
    quoted = ", ".join(f"'{item.value}'" for item in values)
    return f"{column} IN ({quoted})"


class CompanionState(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "companion_states"
    __table_args__ = (
        UniqueConstraint("companion_id", name="uq_companion_states_companion_id"),
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_companion_states_companion_id_companions",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    emotion: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    relationship: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    interaction: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    motivation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class StateEvent(UUIDPrimaryKeyMixin, Base):
    """source_type 用 VARCHAR(32)，因为 dialogue_decision 超过设计稿的 16。"""

    __tablename__ = "state_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_state_events_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_state_events_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_state_events_message_id_messages",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["dialogue_decision_id"],
            ["dialogue_decisions.id"],
            name="fk_state_events_dialogue_decision_id_dialogue_decisions",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("event_type", StateEventType), name="event_type"),
        CheckConstraint(_in_list("source_type", StateSourceType), name="source_type"),
        CheckConstraint("char_length(reason) > 0", name="reason_nonempty"),
        CheckConstraint("version_before IS NULL OR version_before >= 1", name="version_before_positive"),
        CheckConstraint("version_after IS NULL OR version_after >= 1", name="version_after_positive"),
        CheckConstraint(
            "version_before IS NULL OR version_after IS NULL OR version_after > version_before",
            name="version_moves_forward",
        ),
        Index(
            "uq_state_event_version",
            "companion_id",
            "version_after",
            unique=True,
            postgresql_where=text("version_after IS NOT NULL"),
        ),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dialogue_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
