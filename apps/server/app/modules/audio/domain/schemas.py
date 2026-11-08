from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.audio.domain.enums import AudioEngine, AudioTaskStatus, AudioTaskType
from app.modules.audio.domain.expression import AudioExpression


class WorkerHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    asr_backend: str
    tts_backend: str
    asr_loaded: bool
    tts_loaded: bool
    gpu_available: bool
    gpu_name: str | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    queue_depth: int = 0
    reachable: bool = True
    error: str | None = None


class AudioHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    worker: WorkerHealth


class AsrRecognizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companion_id: uuid.UUID
    language: str = "auto"
    conversation_id: uuid.UUID | None = None


class AsrRecognizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    text: str
    language: str | None = None
    emotion: str | None = None
    status: AudioTaskStatus
    duration_ms: int = 0


class TtsSynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companion_id: uuid.UUID
    message_id: uuid.UUID
    voice_profile_id: uuid.UUID | None = None


class TtsSynthesizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    status: AudioTaskStatus
    message_id: uuid.UUID
    audio_url: str | None = None
    format: str | None = None
    sample_rate: int | None = None
    expression: AudioExpression | None = None


class VoiceProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID
    voice_name: str
    engine: AudioEngine | str
    model_name: str
    language: str
    default_speed: float
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AudioTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID
    task_type: AudioTaskType
    task_status: AudioTaskStatus
    message_id: uuid.UUID | None = None
    turn_id: uuid.UUID | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class WorkerAsrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    language: str | None = None
    emotion: str | None = None
    audio_events: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    confidence: float | None = None
    model_name: str
    backend: str


class WorkerTtsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    format: str = "wav"
    sample_rate: int
    duration_ms: int
    model_name: str
    backend: str
