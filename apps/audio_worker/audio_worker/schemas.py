from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    asr_backend: str
    tts_backend: str
    asr_loaded: bool
    tts_loaded: bool
    gpu_available: bool
    gpu_name: str | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    queue_depth: int = 0


class AsrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    language: str | None = None
    emotion: str | None = None
    audio_events: list[str] = Field(default_factory=list)
    duration_ms: int = Field(ge=0)
    confidence: float | None = None
    model_name: str
    backend: str


class TtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    reference_audio_path: str | None = None
    reference_text: str | None = None
    speed: float = Field(default=1.0, gt=0.5, le=2.0)
    volume: float = Field(default=1.0, gt=0.1, le=2.0)
    instruction: str | None = Field(default=None, max_length=500)
    sample_rate: int = Field(default=24000, ge=8000, le=48000)
    provider: str | None = Field(default=None, max_length=32)
    provider_model: str | None = Field(default=None, max_length=128)
    provider_voice_id: str | None = Field(default=None, max_length=128)


class TtsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    format: str = "wav"
    sample_rate: int
    duration_ms: int = Field(ge=0)
    model_name: str
    backend: str
