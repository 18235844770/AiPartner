from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition

FALLBACK_USER_TEXT = "我暂时无法完成这次回复。"
RECENT_MESSAGE_LIMIT = 10


class ModelDecisionSuggestion(BaseModel):
    """模型只提供建议。是否发送由 Python 决定。"""

    model_config = ConfigDict(extra="forbid")

    should_send: bool
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
    def quiet_stands_alone(self) -> "ModelDecisionSuggestion":
        if self.primary_action == DialogueAction.QUIET and self.secondary_actions:
            raise ValueError("Quiet 不能搭配其他行为")
        if self.primary_action in self.secondary_actions:
            raise ValueError("辅助行为不能与主要行为相同")
        return self


def user_fallback() -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=True,
        primary_action=DialogueAction.RESPOND,
        motivation=DecisionMotivation(primary="保守降级", summary="决策模型不可用"),
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("0"),
        reasoning_summary="决策模型不可用，改为简短回应",
    )


def proactive_fallback() -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=False,
        primary_action=DialogueAction.QUIET,
        motivation=DecisionMotivation(primary="保守降级", summary="决策模型不可用"),
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("0"),
        reasoning_summary="决策模型不可用，不主动发送",
    )


def blocked_proactive() -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=False,
        primary_action=DialogueAction.QUIET,
        motivation=DecisionMotivation(primary="遵守交流约束"),
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("1"),
        reasoning_summary="当前不允许主动交流",
    )
