import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.infrastructure.domain.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ModelCallStatus,
    ModelConfigKey,
    ModelProvider,
    ModelTaskType,
)
from app.modules.infrastructure.domain.secrets import reject_secret_keys


class ModelConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(min_length=1, max_length=128)
    parameters: dict[str, object] = Field(default_factory=dict)
    is_enabled: bool = True
    is_default: bool = True

    @field_validator("model_name")
    @classmethod
    def strip_model_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("parameters")
    @classmethod
    def reject_secrets(cls, value: dict[str, object]) -> dict[str, object]:
        reject_secret_keys(value)
        return value

    @model_validator(mode="after")
    def default_must_be_enabled(self) -> "ModelConfigBody":
        if self.is_default and not self.is_enabled:
            raise ValueError("默认配置必须启用")
        return self


class CreateModelConfigRequest(ModelConfigBody):
    config_key: ModelConfigKey


class AddModelConfigVersionRequest(ModelConfigBody):
    pass


class RollbackModelConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class ModelConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    config_key: ModelConfigKey
    provider: ModelProvider
    model_name: str
    task_type: ModelTaskType
    parameters: dict[str, object]
    is_enabled: bool
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime


class RecordModelCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID | None = None
    companion_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    dialogue_decision_id: uuid.UUID | None = None
    background_task_id: uuid.UUID | None = None
    config_id: uuid.UUID | None = None
    trace_id: uuid.UUID
    task_type: ModelTaskType
    provider: ModelProvider
    model_name: str = Field(min_length=1, max_length=128)
    status: ModelCallStatus
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime

    @field_validator("model_name")
    @classmethod
    def strip_model_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("error_code", "error_message")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def scope_and_failure(self) -> "RecordModelCallRequest":
        scoped = self.companion_id is not None or self.conversation_id is not None or self.dialogue_decision_id is not None
        if scoped and (self.user_id is None or self.companion_id is None):
            raise ValueError("关联业务数据时必须提供用户和陪伴者")
        if self.conversation_id is not None and self.companion_id is None:
            raise ValueError("关联业务数据时必须提供用户和陪伴者")
        if self.status in {ModelCallStatus.FAILED, ModelCallStatus.TIMEOUT} and not self.error_message:
            raise ValueError("失败或超时必须记录错误")
        if self.completed_at < self.created_at:
            raise ValueError("完成时间不能早于调用时间")
        return self


class ModelCallLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    dialogue_decision_id: uuid.UUID | None
    background_task_id: uuid.UUID | None
    config_id: uuid.UUID | None
    trace_id: uuid.UUID
    task_type: ModelTaskType
    provider: ModelProvider
    model_name: str
    status: ModelCallStatus
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime


class CreateBackgroundTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID | None = None
    companion_id: uuid.UUID | None = None
    task_type: BackgroundTaskType
    task_key: str = Field(min_length=1, max_length=128)
    queue_name: str = Field(min_length=1, max_length=32)
    payload: dict[str, object] = Field(default_factory=dict)
    max_retries: int = Field(ge=0)
    scheduled_at: datetime

    @field_validator("task_key", "queue_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("payload")
    @classmethod
    def reject_secrets(cls, value: dict[str, object]) -> dict[str, object]:
        reject_secret_keys(value)
        return value

    @model_validator(mode="after")
    def companion_needs_user(self) -> "CreateBackgroundTaskRequest":
        if self.companion_id is not None and self.user_id is None:
            raise ValueError("关联陪伴者时必须提供用户")
        return self


class TaskTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BackgroundTaskStatus
    worker_id: str | None = Field(default=None, max_length=128)
    result: dict[str, object] | None = None
    error_message: str | None = None

    @field_validator("worker_id", "error_message")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("result")
    @classmethod
    def reject_secrets(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is not None:
            reject_secret_keys(value)
        return value


class BackgroundTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID | None
    task_type: BackgroundTaskType
    task_key: str
    queue_name: str
    status: BackgroundTaskStatus
    payload: dict[str, object]
    result: dict[str, object] | None
    error_message: str | None
    retry_count: int
    max_retries: int
    scheduled_at: datetime
    dispatched_at: datetime | None
    locked_at: datetime | None
    worker_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
