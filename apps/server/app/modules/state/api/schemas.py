import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.state.domain.enums import StateEventType, StateSourceType
from app.modules.state.domain.snapshots import EmotionInput, EmotionState, InteractionState, MotivationState, RelationshipState


class InitializeStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplyStateChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    source_type: StateSourceType
    reason: str = Field(min_length=1)
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    dialogue_decision_id: uuid.UUID | None = None
    emotion: EmotionInput | None = None
    relationship: RelationshipState | None = None
    interaction: InteractionState | None = None
    motivation: MotivationState | None = None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @model_validator(mode="after")
    def require_a_dimension_and_source_link(self) -> "ApplyStateChangeRequest":
        if self.emotion is None and self.relationship is None and self.interaction is None and self.motivation is None:
            raise ValueError("至少改变一个状态维度")
        if self.source_type == StateSourceType.USER_MESSAGE and self.message_id is None:
            raise ValueError("用户消息来源必须关联消息")
        if self.source_type == StateSourceType.DIALOGUE_DECISION and self.dialogue_decision_id is None:
            raise ValueError("决策来源必须关联决策")
        return self


class StateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID
    version: int
    updated_at: datetime
    emotion: EmotionState
    relationship: RelationshipState
    interaction: InteractionState
    motivation: MotivationState


class StateEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID
    event_type: StateEventType
    source_type: StateSourceType
    conversation_id: uuid.UUID | None
    message_id: uuid.UUID | None
    dialogue_decision_id: uuid.UUID | None
    version_before: int | None
    version_after: int | None
    changes: dict[str, object]
    reason: str
    created_at: datetime
