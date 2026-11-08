import base64
import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AudioStarted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    message_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    format: str = "wav"
    sample_rate: int = Field(ge=8000)
    sequence: int = Field(ge=0)


class AudioChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    message_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    chunk_index: int = Field(ge=0)
    sample_rate: int = Field(ge=8000)
    format: str = "wav"
    data_base64: str = Field(min_length=1)
    is_last: bool = False
    sequence: int = Field(ge=0)


class AudioCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    message_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    audio_url: str | None = None
    format: str = "wav"
    sample_rate: int = Field(ge=8000)
    duration_ms: int = Field(ge=0)
    sequence: int = Field(ge=0)


class AudioFailed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    message_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    code: str
    message: str = Field(min_length=1)
    sequence: int = Field(ge=0)


class AudioCancelled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    message_id: uuid.UUID
    turn_id: uuid.UUID | None = None
    sequence: int = Field(ge=0)


AudioStreamEvent = AudioStarted | AudioChunk | AudioCompleted | AudioFailed | AudioCancelled

_EVENT_NAMES: dict[type[BaseModel], str] = {
    AudioStarted: "audio.started",
    AudioChunk: "audio.chunk",
    AudioCompleted: "audio.completed",
    AudioFailed: "audio.failed",
    AudioCancelled: "audio.cancelled",
}


def encode_audio_sse(event: AudioStreamEvent) -> str:
    name = _EVENT_NAMES[type(event)]
    payload = event.model_dump(mode="json", exclude_none=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {name}\ndata: {body}\n\n"


def b64_bytes(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


AudioEventName = Literal[
    "audio.started",
    "audio.chunk",
    "audio.completed",
    "audio.failed",
    "audio.cancelled",
]
