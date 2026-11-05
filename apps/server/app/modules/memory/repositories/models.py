import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.memory.domain.enums import (
    EmbeddingStatus,
    MemoryChangeType,
    MemoryOrigin,
    MemoryRelationType,
    MemorySourceRole,
    MemorySourceType,
    MemoryStatus,
    MemoryType,
)
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID


def _in_list(column: str, values: type) -> str:
    quoted = ", ".join(f"'{item.value}'" for item in values)
    return f"{column} IN ({quoted})"


class Memory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_memories_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["memory_versions.memory_id", "memory_versions.id"],
            name="fk_memories_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(_in_list("memory_type", MemoryType), name="memory_type"),
        CheckConstraint(_in_list("status", MemoryStatus), name="status"),
        CheckConstraint(_in_list("memory_origin", MemoryOrigin), name="memory_origin"),
        CheckConstraint("char_length(memory_category) > 0", name="category_nonempty"),
        CheckConstraint("importance BETWEEN 0 AND 100", name="importance_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("stability BETWEEN 0 AND 1", name="stability_range"),
        CheckConstraint("relevance BETWEEN 0 AND 1", name="relevance_range"),
        CheckConstraint("access_count >= 0", name="access_count_nonnegative"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="valid_range",
        ),
        CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR (status <> 'archived' AND archived_at IS NULL)",
            name="archive_consistency",
        ),
        Index("ix_memories_companion_status", "companion_id", "status"),
        Index("ix_memories_companion_type_status", "companion_id", "memory_type", "status"),
        Index("ix_memories_companion_category", "companion_id", "memory_category"),
        Index("ix_memories_companion_importance", "companion_id", "importance"),
        Index("ix_memories_companion_updated_at", "companion_id", "updated_at"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(16), nullable=False)
    memory_category: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MemoryStatus.CANDIDATE.value,
        server_default=text("'candidate'"),
    )
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=50, server_default=text("50"))
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.500"),
        server_default=text("0.500"),
    )
    stability: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.500"),
        server_default=text("0.500"),
    )
    relevance: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.500"),
        server_default=text("0.500"),
    )
    memory_origin: Mapped[str] = mapped_column(String(16), nullable=False)
    is_inference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "memory_versions"
    __table_args__ = (
        UniqueConstraint("memory_id", "id", name="uq_memory_versions_memory_id"),
        UniqueConstraint("memory_id", "version_number", name="uq_memory_versions_memory_version"),
        ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_versions_memory_id_memories",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("change_type", MemoryChangeType), name="change_type"),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("char_length(content) > 0", name="content_nonempty"),
        CheckConstraint("char_length(change_reason) > 0", name="change_reason_nonempty"),
        CheckConstraint("confidence_snapshot BETWEEN 0 AND 1", name="confidence_snapshot_range"),
    )

    memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_content: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_snapshot: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MemorySource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "memory_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_sources_memory_id_memories",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_memory_sources_message_id_messages",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_memory_id"],
            ["memories.id"],
            name="fk_memory_sources_source_memory_id_memories",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("source_type", MemorySourceType), name="source_type"),
        CheckConstraint(_in_list("source_role", MemorySourceRole), name="source_role"),
        CheckConstraint(
            "("
            "source_type = 'message' AND message_id IS NOT NULL AND source_memory_id IS NULL"
            ") OR ("
            "source_type = 'memory' AND source_memory_id IS NOT NULL AND message_id IS NULL"
            ") OR ("
            "source_type = 'system' AND message_id IS NULL AND source_memory_id IS NULL"
            ")",
            name="source_shape",
        ),
        CheckConstraint(
            "relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1",
            name="relevance_score_range",
        ),
    )

    memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_role: Mapped[str] = mapped_column(String(16), nullable=False)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class MemoryRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relation_type",
            name="uq_memory_relations_endpoints_type",
        ),
        ForeignKeyConstraint(
            ["source_memory_id"],
            ["memories.id"],
            name="fk_memory_relations_source_memory_id_memories",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_memory_id"],
            ["memories.id"],
            name="fk_memory_relations_target_memory_id_memories",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("relation_type", MemoryRelationType), name="relation_type"),
        CheckConstraint("source_memory_id <> target_memory_id", name="distinct_endpoints"),
        CheckConstraint("strength BETWEEN 0 AND 1", name="strength_range"),
    )

    source_memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    strength: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryEmbedding(UUIDPrimaryKeyMixin, Base):
    """向量维度不在模型能力核实前锁定，因此使用不限定维度的 vector。"""

    __tablename__ = "memory_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "memory_version_id",
            "embedding_model",
            name="uq_memory_embeddings_version_model",
        ),
        ForeignKeyConstraint(
            ["memory_version_id"],
            ["memory_versions.id"],
            name="fk_memory_embeddings_memory_version_id_memory_versions",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("status", EmbeddingStatus), name="status"),
        CheckConstraint("char_length(embedding_model) > 0", name="model_nonempty"),
        CheckConstraint("char_length(content_hash) > 0", name="content_hash_nonempty"),
        CheckConstraint(
            "(status = 'completed' AND embedding IS NOT NULL) OR (status <> 'completed')",
            name="completed_has_embedding",
        ),
    )

    memory_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=EmbeddingStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
