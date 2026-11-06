import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.conversation.domain.enums import MESSAGE_STATUS_RECORDED, ContentType, ConversationStatus, MessageStatus
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "companion_id", "id", name="uq_conversations_user_companion_id"),
        UniqueConstraint("companion_id", "id", name="uq_conversations_companion_id"),
        ForeignKeyConstraint(
            ["user_id", "companion_id"],
            ["companions.owner_user_id", "companions.id"],
            name="fk_conversations_user_companion",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint("next_sequence_number >= 1", name="next_sequence_number_positive"),
        CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR (status <> 'archived' AND archived_at IS NULL)",
            name="archive_consistency",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ConversationStatus.ACTIVE.value,
        server_default=text("'active'"),
    )
    next_sequence_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence_number", name="uq_messages_conversation_sequence"),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sender_type IN ('user', 'companion', 'system')", name="sender_type"),
        CheckConstraint("content_type = 'text'", name="content_type"),
        CheckConstraint("char_length(content) > 0", name="content_nonempty"),
        CheckConstraint("char_length(status) > 0", name="status_nonempty"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{item.value}'" for item in MessageStatus) + ")",
            name="status_known",
        ),
        CheckConstraint("sequence_number >= 1", name="sequence_number_positive"),
        Index(
            "uq_message_client_id",
            "conversation_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContentType.TEXT.value,
        server_default=text("'text'"),
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MESSAGE_STATUS_RECORDED,
        server_default=text("'recorded'"),
    )
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
