import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.identity.domain.enums import CompanionStatus


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=64)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    locale: str = Field(default="zh-CN", min_length=1, max_length=16)

    @field_validator("display_name", "timezone", "locale")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class UserResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    timezone: str
    locale: str
    status: str
    created_at: datetime
    updated_at: datetime


class CreateCompanionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("名称不能为空")
        return stripped


class UpdateCompanionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    status: CompanionStatus | None = None
    is_default: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("名称不能为空")
        return stripped


class CompanionResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str
    description: str | None
    status: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
