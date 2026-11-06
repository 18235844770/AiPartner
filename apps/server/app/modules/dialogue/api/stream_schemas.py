import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelOutputError, ModelTimeoutError
from app.shared.exceptions.errors import NotFoundError

TurnOutcome = Literal["replied", "quiet"]
TurnErrorCode = Literal[
    "MODEL_REQUEST_FAILED",
    "MODEL_TIMEOUT",
    "MODEL_OUTPUT_INVALID",
    "DECISION_FAILED",
    "CONTEXT_BUILD_FAILED",
    "INTERNAL_SERVER_ERROR",
]


class TurnErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: TurnErrorCode
    message: str = Field(min_length=1)
    retryable: bool


class TurnStarted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    sequence: int = Field(ge=0)


class MessageStarted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    message_id: uuid.UUID
    role: Literal["companion"]
    sequence: int = Field(ge=0)


class MessageDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    message_id: uuid.UUID
    delta: str
    index: int = Field(ge=0)
    sequence: int = Field(ge=0)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = None
    output_tokens: int | None = None


class MessageCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    message_id: uuid.UUID
    finish_reason: Literal["stop"]
    usage: TokenUsage | None = None
    sequence: int = Field(ge=0)


class TurnCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    outcome: TurnOutcome
    sequence: int = Field(ge=0)


class TurnFailed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    error: TurnErrorBody
    sequence: int = Field(ge=0)


class TurnCancelled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    sequence: int = Field(ge=0)


TurnStreamEvent = (
    TurnStarted | MessageStarted | MessageDelta | MessageCompleted | TurnCompleted | TurnFailed | TurnCancelled
)

_EVENT_NAMES: dict[type[BaseModel], str] = {
    TurnStarted: "turn.started",
    MessageStarted: "message.started",
    MessageDelta: "message.delta",
    MessageCompleted: "message.completed",
    TurnCompleted: "turn.completed",
    TurnFailed: "turn.failed",
    TurnCancelled: "turn.cancelled",
}


def encode_sse(event: TurnStreamEvent) -> str:
    name = _EVENT_NAMES[type(event)]
    payload = event.model_dump(mode="json", exclude_none=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {name}\ndata: {body}\n\n"


def failure_for(exc: Exception) -> TurnErrorBody:
    if isinstance(exc, ModelTimeoutError):
        return TurnErrorBody(code="MODEL_TIMEOUT", message="模型服务暂时不可用", retryable=True)
    if isinstance(exc, ModelOutputError):
        return TurnErrorBody(code="MODEL_OUTPUT_INVALID", message="模型输出不可用", retryable=False)
    if isinstance(exc, ModelAdapterError):
        return TurnErrorBody(code="MODEL_REQUEST_FAILED", message="模型服务暂时不可用", retryable=True)
    if isinstance(exc, NotFoundError):
        return TurnErrorBody(code="CONTEXT_BUILD_FAILED", message="这次交流缺少上下文", retryable=False)
    return TurnErrorBody(code="INTERNAL_SERVER_ERROR", message="这次交流没有完成", retryable=True)
