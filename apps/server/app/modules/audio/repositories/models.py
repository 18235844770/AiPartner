import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.audio.domain.enums import AudioTaskStatus, AudioTaskType
from app.shared.database.base import Base
from app.shared.database.mixins import UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID


def _in_list(column: str, values: type) -> str:
    quoted = ", ".join(f"'{item.value}'" for item in values)
    return f"{column} IN ({quoted})"


class CompanionVoiceProfile(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "companion_voice_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_companion_voice_profiles_companion_id_companions",
            ondelete="RESTRICT",
        ),
        CheckConstraint("char_length(voice_name) > 0", name="voice_name_nonempty"),
        CheckConstraint("char_length(engine) > 0", name="engine_nonempty"),
        CheckConstraint("char_length(model_name) > 0", name="model_name_nonempty"),
        CheckConstraint("char_length(reference_audio_path) > 0", name="reference_path_nonempty"),
        CheckConstraint("default_speed > 0.5 AND default_speed <= 2.0", name="default_speed_range"),
        CheckConstraint("is_default = FALSE OR enabled = TRUE", name="default_is_enabled"),
        Index(
            "uq_companion_voice_default",
            "companion_id",
            unique=True,
            postgresql_where=text("is_default = TRUE AND enabled = TRUE"),
        ),
        Index("ix_companion_voice_profiles_companion", "companion_id"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    voice_name: Mapped[str] = mapped_column(String(64), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    reference_audio_path: Mapped[str] = mapped_column(String(512), nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    default_speed: Mapped[float] = mapped_column(Float, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CompanionVoicePreset(Base):
    """陪伴者当前选中的音色。没有记录时用目录默认音色；local 表示本地合成。"""

    __tablename__ = "companion_voice_presets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_companion_voice_presets_companion_id_companions",
            ondelete="RESTRICT",
        ),
        CheckConstraint("char_length(preset_id) > 0", name="preset_id_nonempty"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    preset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AudioTask(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audio_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_audio_tasks_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_audio_tasks_conversation_id_conversations",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["voice_profile_id"],
            ["companion_voice_profiles.id"],
            name="fk_audio_tasks_voice_profile_id_companion_voice_profiles",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in_list("task_type", AudioTaskType), name="task_type"),
        CheckConstraint(_in_list("task_status", AudioTaskStatus), name="task_status"),
        CheckConstraint(
            "task_type <> 'tts' OR message_id IS NOT NULL",
            name="tts_requires_message",
        ),
        CheckConstraint(
            "(task_status IN ('completed', 'failed', 'cancelled') AND completed_at IS NOT NULL)"
            " OR (task_status NOT IN ('completed', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="terminal_completion",
        ),
        CheckConstraint(
            "task_status NOT IN ('failed') OR (error_message IS NOT NULL AND char_length(error_message) > 0)",
            name="failure_has_error",
        ),
        Index("ix_audio_tasks_companion_created", "companion_id", "created_at"),
        Index("ix_audio_tasks_message", "message_id"),
        Index("ix_audio_tasks_status", "task_status"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    voice_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    task_status: Mapped[str] = mapped_column(String(16), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    speak_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expression_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AudioAsset(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audio_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_audio_assets_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["audio_task_id"],
            ["audio_tasks.id"],
            name="fk_audio_assets_audio_task_id_audio_tasks",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("audio_task_id", name="uq_audio_assets_task"),
        CheckConstraint("char_length(file_path) > 0", name="file_path_nonempty"),
        CheckConstraint("sample_rate >= 8000", name="sample_rate_min"),
        CheckConstraint("duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("file_size >= 0", name="file_size_nonnegative"),
        Index("ix_audio_assets_message", "message_id"),
        Index("ix_audio_assets_companion", "companion_id"),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    audio_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
