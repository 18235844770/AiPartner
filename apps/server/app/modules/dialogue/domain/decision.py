import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition, TriggerType


class DecisionMotivation(BaseModel):
    """本次行为动机，不同于 State 里的持续动机。"""

    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=64)
    summary: str | None = None

    @field_validator("primary")
    @classmethod
    def strip_primary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DecisionTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: str | None = Field(default=None, max_length=64)
    transition: TopicTransition | None = None

    @field_validator("topic_id")
    @classmethod
    def strip_topic_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DecisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_type: TriggerType
    conversation_id: uuid.UUID | None = None
    trigger_message_id: uuid.UUID | None = None
    primary_action: DialogueAction
    secondary_actions: list[DialogueAction] = Field(default_factory=list)
    motivation: DecisionMotivation
    topic: DecisionTopic = Field(default_factory=DecisionTopic)
    confidence: Decimal = Field(ge=0, le=1)
    reasoning_summary: str = Field(min_length=1)

    @field_validator("reasoning_summary")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("secondary_actions")
    @classmethod
    def unique_secondary(cls, value: list[DialogueAction]) -> list[DialogueAction]:
        if len(value) != len(set(value)):
            raise ValueError("辅助行为不能重复")
        if DialogueAction.QUIET in value:
            raise ValueError("Quiet 只能作为独立决策")
        return value

    @model_validator(mode="after")
    def quiet_stands_alone_and_user_message_has_source(self) -> "DecisionProposal":
        if self.primary_action == DialogueAction.QUIET and self.secondary_actions:
            raise ValueError("Quiet 不能搭配其他行为")
        if self.primary_action in self.secondary_actions:
            raise ValueError("辅助行为不能与主要行为相同")
        if self.trigger_type == TriggerType.USER_MESSAGE and self.trigger_message_id is None:
            raise ValueError("用户消息触发必须关联消息")
        return self
