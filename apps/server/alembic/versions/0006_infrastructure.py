"""Infrastructure：模型配置、调用日志和后台任务。配置按版本追加，不覆盖历史。调用日志不保存 Prompt。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_infrastructure"
down_revision: str | None = "0005_dialogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_key", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_configs"),
        sa.UniqueConstraint("config_key", "version", name="uq_model_configs_key_version"),
        sa.CheckConstraint("provider IN ('deepseek')", name="ck_model_configs_provider"),
        sa.CheckConstraint(
            "(config_key = 'conversation_model' AND task_type = 'conversation')"
            " OR (config_key = 'decision_model' AND task_type = 'decision')"
            " OR (config_key = 'memory_model' AND task_type = 'memory')"
            " OR (config_key = 'embedding_model' AND task_type = 'embedding')",
            name="ck_model_configs_config_task_pairing",
        ),
        sa.CheckConstraint("version >= 1", name="ck_model_configs_version_positive"),
        sa.CheckConstraint("char_length(model_name) > 0", name="ck_model_configs_model_name_nonempty"),
        sa.CheckConstraint("is_default = FALSE OR is_enabled = TRUE", name="ck_model_configs_default_is_enabled"),
    )
    op.create_index(
        "uq_model_config_default",
        "model_configs",
        ["task_type"],
        unique=True,
        postgresql_where=sa.text("is_enabled = TRUE AND is_default = TRUE"),
    )
    op.create_table(
        "background_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("task_key", sa.String(128), nullable=False),
        sa.Column("queue_name", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_background_tasks_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_background_tasks"),
        sa.UniqueConstraint("task_key", name="uq_background_tasks_task_key"),
        sa.CheckConstraint(
            "task_type IN ('memory_extract', 'memory_evaluate', 'memory_embedding', 'memory_relation',"
            " 'memory_summarize', 'state_maintenance', 'proactive_check')",
            name="ck_background_tasks_task_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'retrying', 'completed', 'failed', 'cancelled')",
            name="ck_background_tasks_status",
        ),
        sa.CheckConstraint("char_length(task_key) > 0", name="ck_background_tasks_task_key_nonempty"),
        sa.CheckConstraint("char_length(queue_name) > 0", name="ck_background_tasks_queue_name_nonempty"),
        sa.CheckConstraint("retry_count >= 0", name="ck_background_tasks_retry_count_nonnegative"),
        sa.CheckConstraint("max_retries >= 0", name="ck_background_tasks_max_retries_nonnegative"),
        sa.CheckConstraint(
            "retry_count <= max_retries OR status = 'failed'",
            name="ck_background_tasks_retry_limit",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'retrying') AND dispatched_at IS NULL) OR status NOT IN ('pending', 'retrying')",
            name="ck_background_tasks_dispatch_pending",
        ),
        sa.CheckConstraint(
            "status <> 'running' OR (started_at IS NOT NULL AND worker_id IS NOT NULL AND char_length(worker_id) > 0)",
            name="ck_background_tasks_running_worker",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled') AND completed_at IS NOT NULL)"
            " OR (status NOT IN ('completed', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_background_tasks_terminal_completion",
        ),
    )
    op.create_index("ix_background_tasks_status_scheduled", "background_tasks", ["status", "scheduled_at"])
    op.create_index("ix_background_tasks_companion_created", "background_tasks", ["companion_id", "created_at"])
    op.create_index("ix_background_tasks_type_status", "background_tasks", ["task_type", "status"])
    op.create_table(
        "model_call_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dialogue_decision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("background_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_model_call_logs_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_model_call_logs_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dialogue_decision_id"],
            ["dialogue_decisions.id"],
            name="fk_model_call_logs_dialogue_decision_id_dialogue_decisions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["background_task_id"],
            ["background_tasks.id"],
            name="fk_model_call_logs_background_task_id_background_tasks",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["model_configs.id"],
            name="fk_model_call_logs_config_id_model_configs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_call_logs"),
        sa.CheckConstraint(
            "task_type IN ('conversation', 'decision', 'memory', 'embedding')",
            name="ck_model_call_logs_task_type",
        ),
        sa.CheckConstraint("provider IN ('deepseek')", name="ck_model_call_logs_provider"),
        sa.CheckConstraint(
            "status IN ('success', 'failed', 'timeout', 'cancelled')",
            name="ck_model_call_logs_status",
        ),
        sa.CheckConstraint("char_length(model_name) > 0", name="ck_model_call_logs_model_name_nonempty"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_model_call_logs_latency_nonnegative"),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_model_call_logs_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_model_call_logs_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "status NOT IN ('failed', 'timeout') OR (error_message IS NOT NULL AND char_length(error_message) > 0)",
            name="ck_model_call_logs_failure_has_error",
        ),
    )
    op.create_index("ix_model_call_logs_trace_id", "model_call_logs", ["trace_id"])
    op.create_index("ix_model_call_logs_companion_created", "model_call_logs", ["companion_id", "created_at"])
    op.create_index("ix_model_call_logs_task_created", "model_call_logs", ["task_type", "created_at"])
    op.create_index("ix_model_call_logs_status_created", "model_call_logs", ["status", "created_at"])
    op.create_index("ix_model_call_logs_decision", "model_call_logs", ["dialogue_decision_id"])


def downgrade() -> None:
    op.drop_index("ix_model_call_logs_decision", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_status_created", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_task_created", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_companion_created", table_name="model_call_logs")
    op.drop_index("ix_model_call_logs_trace_id", table_name="model_call_logs")
    op.drop_table("model_call_logs")
    op.drop_index("ix_background_tasks_type_status", table_name="background_tasks")
    op.drop_index("ix_background_tasks_companion_created", table_name="background_tasks")
    op.drop_index("ix_background_tasks_status_scheduled", table_name="background_tasks")
    op.drop_table("background_tasks")
    op.drop_index("uq_model_config_default", table_name="model_configs")
    op.drop_table("model_configs")
