import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.memory.domain.enums import (
    EmbeddingStatus,
    MemoryChangeType,
    MemoryOrigin,
    MemoryRelationType,
    MemorySourceRole,
    MemorySourceType,
    MemoryType,
)
from app.modules.model_adapter.domain.embedding import EMBEDDING_DIMENSIONS


class MemorySourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: MemorySourceType
    source_role: MemorySourceRole
    message_id: uuid.UUID | None = None
    source_memory_id: uuid.UUID | None = None
    relevance_score: Decimal | None = Field(default=None, ge=0, le=1)


class CreateMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType
    memory_category: str = Field(min_length=1, max_length=32)
    subject: str | None = Field(default=None, max_length=128)
    memory_origin: MemoryOrigin
    is_inference: bool = False
    content: str = Field(min_length=1)
    summary: str | None = None
    structured_content: dict[str, object] = Field(default_factory=dict)
    change_reason: str = Field(min_length=1)
    sources: list[MemorySourceInput] = Field(default_factory=list)

    @field_validator("memory_category", "content", "change_reason")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("subject", "summary")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def working_context_is_not_a_memory(self) -> "CreateMemoryRequest":
        if self.memory_type == MemoryType.WORKING:
            raise ValueError("工作记忆写入 working_memories，不能作为正式记忆")
        return self


class CreateMemoryVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: MemoryChangeType
    change_reason: str = Field(min_length=1)
    content: str = Field(min_length=1)
    summary: str | None = None
    structured_content: dict[str, object] | None = None

    @field_validator("change_reason", "content")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("change_type")
    @classmethod
    def reject_create(cls, value: MemoryChangeType) -> MemoryChangeType:
        if value == MemoryChangeType.CREATE:
            raise ValueError("后续版本不能使用 create")
        return value


class CreateMemoryRelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_memory_id: uuid.UUID
    relation_type: MemoryRelationType
    strength: Decimal = Field(ge=0, le=1)
    description: str | None = None


class RecordEmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_model: str = Field(min_length=1, max_length=64)
    status: EmbeddingStatus
    embedding: list[float] | None = None

    @field_validator("embedding_model")
    @classmethod
    def strip_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("embedding")
    @classmethod
    def completed_needs_values(cls, value: list[float] | None, info) -> list[float] | None:
        if value is not None and len(value) != EMBEDDING_DIMENSIONS:
            raise ValueError("向量维度必须是 1024")
        status = info.data.get("status")
        if status == EmbeddingStatus.COMPLETED and not value:
            raise ValueError("完成状态必须带有向量")
        return value


class MemoryVersionResponse(BaseModel):
    id: uuid.UUID
    version_number: int
    content: str
    summary: str | None
    structured_content: dict[str, object]
    change_type: str
    change_reason: str
    confidence_snapshot: Decimal
    created_at: datetime


class MemorySourceResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    source_role: str
    message_id: uuid.UUID | None
    source_memory_id: uuid.UUID | None
    relevance_score: Decimal | None


class MemoryRelationResponse(BaseModel):
    id: uuid.UUID
    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID


class MemoryEmbeddingResponse(BaseModel):
    id: uuid.UUID
    status: str


class MemoryResponse(BaseModel):
    id: uuid.UUID
    companion_id: uuid.UUID
    memory_type: str
    memory_category: str
    subject: str | None
    status: str
    memory_origin: str
    is_inference: bool
    importance: int
    confidence: Decimal
    current_version_id: uuid.UUID
    current_version: MemoryVersionResponse
    sources: list[MemorySourceResponse]
    created_at: datetime
    updated_at: datetime
