import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.persona.domain.archive import PersonaArchive
from app.modules.persona.domain.enums import MbtiType


class InitializePersonaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mbti_type: MbtiType | None = None


class CreatePersonaVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_reason: str = Field(min_length=1)
    core_traits: dict[str, object] | None = None
    behavior_traits: dict[str, object] | None = None
    communication_preferences: dict[str, object] | None = None
    archive: PersonaArchive | None = None

    @field_validator("change_reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("core_traits", "behavior_traits", "communication_preferences")
    @classmethod
    def reject_mbti_override(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is not None and "mbti_type" in value:
            raise ValueError("核心人格类型不能通过细节变更修改")
        return value


class PersonaVersionResponse(BaseModel):
    id: uuid.UUID
    persona_profile_id: uuid.UUID
    version_number: int
    mbti_type: str
    core_traits: dict[str, object]
    behavior_traits: dict[str, object]
    communication_preferences: dict[str, object]
    archive: dict[str, object]
    change_reason: str
    created_at: datetime


class PersonaResponse(BaseModel):
    id: uuid.UUID
    companion_id: uuid.UUID
    initial_version_id: uuid.UUID
    current_version_id: uuid.UUID
    current_version: PersonaVersionResponse
    created_at: datetime
    updated_at: datetime
