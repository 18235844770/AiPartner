"""Memory 主体、版本、来源、关系和向量。向量维度暂不锁定。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003_memory"
down_revision: str | None = "0002_persona"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(16), nullable=False),
        sa.Column("memory_category", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'candidate'")),
        sa.Column("importance", sa.SmallInteger(), nullable=False, server_default=sa.text("50")),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")),
        sa.Column("stability", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")),
        sa.Column("relevance", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")),
        sa.Column("memory_origin", sa.String(16), nullable=False),
        sa.Column("is_inference", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_memories_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memories"),
        sa.CheckConstraint(
            "memory_type IN ('working', 'semantic', 'episodic')",
            name="ck_memories_memory_type",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'pending', 'active', 'archived', 'rejected')",
            name="ck_memories_status",
        ),
        sa.CheckConstraint(
            "memory_origin IN ('user_explicit', 'user_behavior', 'ai_inference', 'ai_interest', 'system_generated')",
            name="ck_memories_memory_origin",
        ),
        sa.CheckConstraint("char_length(memory_category) > 0", name="ck_memories_category_nonempty"),
        sa.CheckConstraint("importance BETWEEN 0 AND 100", name="ck_memories_importance_range"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memories_confidence_range"),
        sa.CheckConstraint("stability BETWEEN 0 AND 1", name="ck_memories_stability_range"),
        sa.CheckConstraint("relevance BETWEEN 0 AND 1", name="ck_memories_relevance_range"),
        sa.CheckConstraint("access_count >= 0", name="ck_memories_access_count_nonnegative"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_memories_valid_range",
        ),
        sa.CheckConstraint(
            "(status = 'archived' AND archived_at IS NOT NULL) OR (status <> 'archived' AND archived_at IS NULL)",
            name="ck_memories_archive_consistency",
        ),
    )
    op.create_index("ix_memories_companion_status", "memories", ["companion_id", "status"])
    op.create_index("ix_memories_companion_type_status", "memories", ["companion_id", "memory_type", "status"])
    op.create_index("ix_memories_companion_category", "memories", ["companion_id", "memory_category"])
    op.create_index("ix_memories_companion_importance", "memories", ["companion_id", "importance"])
    op.create_index("ix_memories_companion_updated_at", "memories", ["companion_id", "updated_at"])
    op.create_table(
        "memory_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_content", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("change_type", sa.String(16), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("confidence_snapshot", sa.Numeric(4, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_versions_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_versions"),
        sa.UniqueConstraint("memory_id", "id", name="uq_memory_versions_memory_id"),
        sa.UniqueConstraint("memory_id", "version_number", name="uq_memory_versions_memory_version"),
        sa.CheckConstraint(
            "change_type IN ('create', 'supplement', 'correct', 'update', 'merge')",
            name="ck_memory_versions_change_type",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_memory_versions_version_number_positive"),
        sa.CheckConstraint("char_length(content) > 0", name="ck_memory_versions_content_nonempty"),
        sa.CheckConstraint("char_length(change_reason) > 0", name="ck_memory_versions_change_reason_nonempty"),
        sa.CheckConstraint(
            "confidence_snapshot BETWEEN 0 AND 1",
            name="ck_memory_versions_confidence_snapshot_range",
        ),
    )
    op.create_foreign_key(
        "fk_memories_current_version",
        "memories",
        "memory_versions",
        ["id", "current_version_id"],
        ["memory_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "memory_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_memory_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_role", sa.String(16), nullable=False),
        sa.Column("relevance_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_sources_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_memory_sources_message_id_messages",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_memory_id"],
            ["memories.id"],
            name="fk_memory_sources_source_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_sources"),
        sa.CheckConstraint("source_type IN ('message', 'memory', 'system')", name="ck_memory_sources_source_type"),
        sa.CheckConstraint(
            "source_role IN ('evidence', 'context', 'correction')",
            name="ck_memory_sources_source_role",
        ),
        sa.CheckConstraint(
            "("
            "source_type = 'message' AND message_id IS NOT NULL AND source_memory_id IS NULL"
            ") OR ("
            "source_type = 'memory' AND source_memory_id IS NOT NULL AND message_id IS NULL"
            ") OR ("
            "source_type = 'system' AND message_id IS NULL AND source_memory_id IS NULL"
            ")",
            name="ck_memory_sources_source_shape",
        ),
        sa.CheckConstraint(
            "relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1",
            name="ck_memory_sources_relevance_score_range",
        ),
    )
    op.create_table(
        "memory_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(24), nullable=False),
        sa.Column("strength", sa.Numeric(4, 3), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["source_memory_id"],
            ["memories.id"],
            name="fk_memory_relations_source_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_memory_id"],
            ["memories.id"],
            name="fk_memory_relations_target_memory_id_memories",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_relations"),
        sa.UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relation_type",
            name="uq_memory_relations_endpoints_type",
        ),
        sa.CheckConstraint(
            "relation_type IN ('related_to', 'supports', 'contradicts', 'supersedes', 'caused_by', 'part_of')",
            name="ck_memory_relations_relation_type",
        ),
        sa.CheckConstraint("source_memory_id <> target_memory_id", name="ck_memory_relations_distinct_endpoints"),
        sa.CheckConstraint("strength BETWEEN 0 AND 1", name="ck_memory_relations_strength_range"),
    )
    op.create_table(
        "memory_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["memory_version_id"],
            ["memory_versions.id"],
            name="fk_memory_embeddings_memory_version_id_memory_versions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_embeddings"),
        sa.UniqueConstraint("memory_version_id", "embedding_model", name="uq_memory_embeddings_version_model"),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name="ck_memory_embeddings_status"),
        sa.CheckConstraint("char_length(embedding_model) > 0", name="ck_memory_embeddings_model_nonempty"),
        sa.CheckConstraint("char_length(content_hash) > 0", name="ck_memory_embeddings_content_hash_nonempty"),
        sa.CheckConstraint(
            "(status = 'completed' AND embedding IS NOT NULL) OR (status <> 'completed')",
            name="ck_memory_embeddings_completed_has_embedding",
        ),
    )


def downgrade() -> None:
    op.drop_table("memory_embeddings")
    op.drop_table("memory_relations")
    op.drop_table("memory_sources")
    op.drop_constraint("fk_memories_current_version", "memories", type_="foreignkey")
    op.drop_table("memory_versions")
    op.drop_index("ix_memories_companion_updated_at", table_name="memories")
    op.drop_index("ix_memories_companion_importance", table_name="memories")
    op.drop_index("ix_memories_companion_category", table_name="memories")
    op.drop_index("ix_memories_companion_type_status", table_name="memories")
    op.drop_index("ix_memories_companion_status", table_name="memories")
    op.drop_table("memories")
