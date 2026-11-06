import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.memory.domain.enums import AttentionOrigin, AttentionStatus, OpenThreadStatus


class OpenThreadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    status: OpenThreadStatus = OpenThreadStatus.OPEN
    message_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class SaveWorkingMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    current_topic: str | None = Field(default=None, max_length=128)
    attention_topic_id: uuid.UUID | None = None
    open_threads: list[OpenThreadInput] = Field(default_factory=list)
    expires_at: datetime | None = None
    archived: bool = False
    version: int | None = Field(default=None, ge=1)

    @field_validator("summary", "current_topic")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class WorkingMemoryResponse(BaseModel):
    id: uuid.UUID
    companion_id: uuid.UUID
    conversation_id: uuid.UUID
    summary: str | None
    current_topic: str | None
    attention_topic_id: uuid.UUID | None
    open_threads: list[dict[str, object]]
    expires_at: datetime | None
    archived_at: datetime | None
    version: int


class CreateAttentionTopicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    description: str | None = None
    origin_type: AttentionOrigin
    interest_score: Decimal = Field(default=Decimal("0.500"), ge=0, le=1)
    next_review_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class LinkAttentionMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: uuid.UUID


class AttentionTopicResponse(BaseModel):
    id: uuid.UUID
    companion_id: uuid.UUID
    title: str
    description: str | None
    origin_type: str
    status: str
    interest_score: Decimal
    last_discussed_at: datetime | None
    next_review_at: datetime | None
    memory_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class UpdateAttentionStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AttentionStatus
