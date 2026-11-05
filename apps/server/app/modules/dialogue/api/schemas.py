import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.dialogue.domain.decision import DecisionProposal
from app.modules.dialogue.domain.enums import DecisionStatus, DialogueAction, TriggerType


class RecordDecisionRequest(DecisionProposal):
    pass


class RealizeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class UserTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    client_message_id: uuid.UUID | None = None

    @field_validator("content")
    @classmethod
    def strip_turn_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class ProactiveTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    companion_id: uuid.UUID
    conversation_id: uuid.UUID | None
    trigger_message_id: uuid.UUID | None
    result_message_id: uuid.UUID | None
    trigger_type: TriggerType
    primary_action: DialogueAction
    secondary_actions: list[DialogueAction]
    motivation: dict[str, object]
    topic: dict[str, object]
    confidence: Decimal
    reasoning_summary: str
    status: DecisionStatus
    created_at: datetime
    completed_at: datetime | None


class TurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message_id: uuid.UUID | None
    companion_message_id: uuid.UUID | None
    decision: DecisionResponse
