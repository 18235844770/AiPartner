import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.infrastructure.domain.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ModelCallStatus,
    ModelConfigKey,
    ModelProvider,
    ModelTaskType,
)
from app.shared.database.base import Base
from app.shared.database.mixins import UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID

_CONFIG_PAIRING = " OR ".join(
    f"(config_key = '{key.value}' AND task_type = '{task.value}')"
    for key, task in (
        (ModelConfigKey.CONVERSATION, ModelTaskType.CONVERSATION),
        (ModelConfigKey.DECISION, ModelTaskType.DECISION),
        (ModelConfigKey.MEMORY, ModelTaskType.MEMORY),
        (ModelConfigKey.EMBEDDING, ModelTaskType.EMBEDDING),
    )
)


def _in_list(column: str, values: type) -> str:
    quoted = ", ".join(f"'{item.value}'" for item in values)
    return f"{column} IN ({quoted})"


class ModelConfig(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        UniqueConstraint("config_key", "version", name="uq_model_configs_key_version"),
        CheckConstraint(_in_list("provider", ModelProvider), name="provider"),
        CheckConstraint(_CONFIG_PAIRING, name="config_task_pairing"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("char_length(model_name) > 0", name="model_name_nonempty"),
        CheckConstraint("is_default = FALSE OR is_enabled = TRUE", name="default_is_enabled"),
        Index(
            "uq_model_config_default",
            "task_type",
            unique=True,
            postgresql_where=text("is_enabled = TRUE AND is_default = TRUE"),
        ),
    )

    config_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundTask(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "background_tasks"
    __table_args__ = (
        UniqueConstraint("task_key", name="uq_background_tasks_task_key"),
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_background_tasks_companion_id_companions",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("task_type", BackgroundTaskType), name="task_type"),
        CheckConstraint(_in_list("status", BackgroundTaskStatus), name="status"),
        CheckConstraint("char_length(task_key) > 0", name="task_key_nonempty"),
        CheckConstraint("char_length(queue_name) > 0", name="queue_name_nonempty"),
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        CheckConstraint("max_retries >= 0", name="max_retries_nonnegative"),
        CheckConstraint("retry_count <= max_retries OR status = 'failed'", name="retry_limit"),
        CheckConstraint(
            "(status IN ('pending', 'retrying') AND dispatched_at IS NULL) OR status NOT IN ('pending', 'retrying')",
            name="dispatch_pending",
        ),
        CheckConstraint(
            "status <> 'running' OR (started_at IS NOT NULL AND worker_id IS NOT NULL AND char_length(worker_id) > 0)",
            name="running_worker",
        ),
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled') AND completed_at IS NOT NULL)"
            " OR (status NOT IN ('completed', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="terminal_completion",
        ),
        Index("ix_background_tasks_status_scheduled", "status", "scheduled_at"),
        Index("ix_background_tasks_companion_created", "companion_id", "created_at"),
        Index("ix_background_tasks_type_status", "task_type", "status"),
    )

    companion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    task_key: Mapped[str] = mapped_column(String(128), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelCallLog(UUIDPrimaryKeyMixin, Base):
    """不保存完整 Prompt 和完整模型输出。"""

    __tablename__ = "model_call_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_model_call_logs_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_model_call_logs_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["dialogue_decision_id"],
            ["dialogue_decisions.id"],
            name="fk_model_call_logs_dialogue_decision_id_dialogue_decisions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["background_task_id"],
            ["background_tasks.id"],
            name="fk_model_call_logs_background_task_id_background_tasks",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["config_id"],
            ["model_configs.id"],
            name="fk_model_call_logs_config_id_model_configs",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("task_type", ModelTaskType), name="task_type"),
        CheckConstraint(_in_list("provider", ModelProvider), name="provider"),
        CheckConstraint(_in_list("status", ModelCallStatus), name="status"),
        CheckConstraint("char_length(model_name) > 0", name="model_name_nonempty"),
        CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_nonnegative"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_nonnegative"),
        CheckConstraint(
            "status NOT IN ('failed', 'timeout') OR (error_message IS NOT NULL AND char_length(error_message) > 0)",
            name="failure_has_error",
        ),
        Index("ix_model_call_logs_trace_id", "trace_id"),
        Index("ix_model_call_logs_companion_created", "companion_id", "created_at"),
        Index("ix_model_call_logs_task_created", "task_type", "created_at"),
        Index("ix_model_call_logs_status_created", "status", "created_at"),
        Index("ix_model_call_logs_decision", "dialogue_decision_id"),
    )

    companion_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dialogue_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    background_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    config_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
