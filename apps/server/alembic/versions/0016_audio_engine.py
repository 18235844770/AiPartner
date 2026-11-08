"""Audio Engine：音色配置、ASR/TTS 任务与资产；模型配置增加 asr_model/tts_model。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_audio_engine"
down_revision: str | None = "0015_rel_self_assertion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_model_configs_config_task_pairing", "model_configs", type_="check")
    op.create_check_constraint(
        "ck_model_configs_config_task_pairing",
        "model_configs",
        "(config_key = 'conversation_model' AND task_type = 'conversation')"
        " OR (config_key = 'decision_model' AND task_type = 'decision')"
        " OR (config_key = 'memory_model' AND task_type = 'memory')"
        " OR (config_key = 'embedding_model' AND task_type = 'embedding')"
        " OR (config_key = 'asr_model' AND task_type = 'asr')"
        " OR (config_key = 'tts_model' AND task_type = 'tts')",
    )
    op.drop_constraint("ck_model_call_logs_task_type", "model_call_logs", type_="check")
    op.create_check_constraint(
        "ck_model_call_logs_task_type",
        "model_call_logs",
        "task_type IN ('conversation', 'decision', 'memory', 'embedding', 'asr', 'tts')",
    )

    op.create_table(
        "companion_voice_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("voice_name", sa.String(length=64), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("reference_audio_path", sa.String(length=512), nullable=False),
        sa.Column("reference_text", sa.Text(), nullable=False),
        sa.Column("reference_checksum", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("default_speed", sa.Float(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_companion_voice_profiles_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companion_voice_profiles"),
        sa.CheckConstraint("char_length(voice_name) > 0", name="ck_companion_voice_profiles_voice_name_nonempty"),
        sa.CheckConstraint("char_length(engine) > 0", name="ck_companion_voice_profiles_engine_nonempty"),
        sa.CheckConstraint("char_length(model_name) > 0", name="ck_companion_voice_profiles_model_name_nonempty"),
        sa.CheckConstraint(
            "char_length(reference_audio_path) > 0",
            name="ck_companion_voice_profiles_reference_path_nonempty",
        ),
        sa.CheckConstraint(
            "default_speed > 0.5 AND default_speed <= 2.0",
            name="ck_companion_voice_profiles_default_speed_range",
        ),
        sa.CheckConstraint(
            "is_default = FALSE OR enabled = TRUE",
            name="ck_companion_voice_profiles_default_is_enabled",
        ),
    )
    op.create_index(
        "uq_companion_voice_default",
        "companion_voice_profiles",
        ["companion_id"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE AND enabled = TRUE"),
    )
    op.create_index(
        "ix_companion_voice_profiles_companion",
        "companion_voice_profiles",
        ["companion_id"],
    )

    op.create_table(
        "audio_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("voice_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_type", sa.String(length=16), nullable=False),
        sa.Column("task_status", sa.String(length=16), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("speak_text", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("expression_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_audio_tasks_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_audio_tasks_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"],
            ["companion_voice_profiles.id"],
            name="fk_audio_tasks_voice_profile_id_companion_voice_profiles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audio_tasks"),
        sa.CheckConstraint("task_type IN ('asr', 'tts')", name="ck_audio_tasks_task_type"),
        sa.CheckConstraint(
            "task_status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_audio_tasks_task_status",
        ),
        sa.CheckConstraint("task_type <> 'tts' OR message_id IS NOT NULL", name="ck_audio_tasks_tts_requires_message"),
        sa.CheckConstraint(
            "(task_status IN ('completed', 'failed', 'cancelled') AND completed_at IS NOT NULL)"
            " OR (task_status NOT IN ('completed', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_audio_tasks_terminal_completion",
        ),
        sa.CheckConstraint(
            "task_status NOT IN ('failed') OR (error_message IS NOT NULL AND char_length(error_message) > 0)",
            name="ck_audio_tasks_failure_has_error",
        ),
    )
    op.create_index("ix_audio_tasks_companion_created", "audio_tasks", ["companion_id", "created_at"])
    op.create_index("ix_audio_tasks_message", "audio_tasks", ["message_id"])
    op.create_index("ix_audio_tasks_status", "audio_tasks", ["task_status"])

    op.create_table(
        "audio_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audio_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_audio_assets_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audio_task_id"],
            ["audio_tasks.id"],
            name="fk_audio_assets_audio_task_id_audio_tasks",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audio_assets"),
        sa.UniqueConstraint("audio_task_id", name="uq_audio_assets_task"),
        sa.CheckConstraint("char_length(file_path) > 0", name="ck_audio_assets_file_path_nonempty"),
        sa.CheckConstraint("sample_rate >= 8000", name="ck_audio_assets_sample_rate_min"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_audio_assets_duration_nonnegative"),
        sa.CheckConstraint("file_size >= 0", name="ck_audio_assets_file_size_nonnegative"),
    )
    op.create_index("ix_audio_assets_message", "audio_assets", ["message_id"])
    op.create_index("ix_audio_assets_companion", "audio_assets", ["companion_id"])


def downgrade() -> None:
    op.drop_index("ix_audio_assets_companion", table_name="audio_assets")
    op.drop_index("ix_audio_assets_message", table_name="audio_assets")
    op.drop_table("audio_assets")
    op.drop_index("ix_audio_tasks_status", table_name="audio_tasks")
    op.drop_index("ix_audio_tasks_message", table_name="audio_tasks")
    op.drop_index("ix_audio_tasks_companion_created", table_name="audio_tasks")
    op.drop_table("audio_tasks")
    op.drop_index("ix_companion_voice_profiles_companion", table_name="companion_voice_profiles")
    op.drop_index("uq_companion_voice_default", table_name="companion_voice_profiles")
    op.drop_table("companion_voice_profiles")

    op.execute("DELETE FROM model_call_logs WHERE task_type IN ('asr', 'tts')")
    op.execute("DELETE FROM model_configs WHERE config_key IN ('asr_model', 'tts_model')")
    op.drop_constraint("ck_model_call_logs_task_type", "model_call_logs", type_="check")
    op.create_check_constraint(
        "ck_model_call_logs_task_type",
        "model_call_logs",
        "task_type IN ('conversation', 'decision', 'memory', 'embedding')",
    )
    op.drop_constraint("ck_model_configs_config_task_pairing", "model_configs", type_="check")
    op.create_check_constraint(
        "ck_model_configs_config_task_pairing",
        "model_configs",
        "(config_key = 'conversation_model' AND task_type = 'conversation')"
        " OR (config_key = 'decision_model' AND task_type = 'decision')"
        " OR (config_key = 'memory_model' AND task_type = 'memory')"
        " OR (config_key = 'embedding_model' AND task_type = 'embedding')",
    )
