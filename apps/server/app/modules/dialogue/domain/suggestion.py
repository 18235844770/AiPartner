from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition

FALLBACK_USER_TEXT = "我暂时无法完成这次回复。"
RECENT_MESSAGE_LIMIT = 10


class UserNeed(BaseModel):
    """用户这一轮的交流需求。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=200)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class SelfMotivation(BaseModel):
    """陪伴者自己对当前内容的兴趣、观点和表达欲望。"""

    model_config = ConfigDict(extra="forbid")

    interest: str = Field(min_length=1, max_length=200)
    viewpoint: str = Field(min_length=1, max_length=200)
    desire_to_express: str = Field(min_length=1, max_length=200)

    @field_validator("interest", "viewpoint", "desire_to_express", mode="before")
    @classmethod
    def missing_means_none(cls, value: object) -> object:
        if value is None:
            return "没有"
        return value

    @field_validator("interest", "viewpoint", "desire_to_express")
    @classmethod
    def strip_part(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class ModelDecisionSuggestion(BaseModel):
    """模型只提供建议。是否发送由 Python 决定。"""

    model_config = ConfigDict(extra="forbid")

    should_send: bool
    primary_action: DialogueAction
    secondary_actions: list[DialogueAction] = Field(default_factory=list)
    motivation: DecisionMotivation
    user_need: UserNeed
    self_motivation: SelfMotivation
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
        blob = " ".join(
            [
                self.motivation.primary,
                self.motivation.summary or "",
                self.reasoning_summary,
                self.user_need.summary,
                self.self_motivation.interest,
                self.self_motivation.viewpoint,
                self.self_motivation.desire_to_express,
            ]
        )
        if assistant_self_reference(blob):
            raise ValueError("不能把自己写成助手")
        return self


def assistant_self_reference(text: str) -> bool:
    """去掉明确的否定说法后，仍把说话者称作助手。"""
    cleaned = text
    for allowed in ("不是助手", "非助手", "不要写成助手", "不要把自己写成助手", "助手化"):
        cleaned = cleaned.replace(allowed, "")
    return "助手" in cleaned


def considered_exchange(user_summary: str, desire: str) -> tuple[UserNeed, SelfMotivation]:
    return (
        UserNeed(summary=user_summary),
        SelfMotivation(
            interest="没有必须接上的个人兴趣",
            viewpoint="这次没有完成自己的判断",
            desire_to_express=desire,
        ),
    )


def user_fallback() -> ModelDecisionSuggestion:
    user_need, self_motivation = considered_exchange("用户在等这一轮的回应", "只说明暂时无法完成")
    return ModelDecisionSuggestion(
        should_send=True,
        primary_action=DialogueAction.RESPOND,
        motivation=DecisionMotivation(primary="保守降级", summary="决策模型不可用"),
        user_need=user_need,
        self_motivation=self_motivation,
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("0"),
        reasoning_summary="决策模型不可用，改为简短回应",
    )


def proactive_fallback() -> ModelDecisionSuggestion:
    user_need, self_motivation = considered_exchange("没有新的用户输入", "没有把握时不主动说")
    return ModelDecisionSuggestion(
        should_send=False,
        primary_action=DialogueAction.QUIET,
        motivation=DecisionMotivation(primary="保守降级", summary="决策模型不可用"),
        user_need=user_need,
        self_motivation=self_motivation,
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("0"),
        reasoning_summary="决策模型不可用，不主动发送",
    )


def blocked_proactive() -> ModelDecisionSuggestion:
    user_need, self_motivation = considered_exchange("没有等待中的用户请求", "想说也不在当前允许的时候说")
    return ModelDecisionSuggestion(
        should_send=False,
        primary_action=DialogueAction.QUIET,
        motivation=DecisionMotivation(primary="遵守交流约束"),
        user_need=user_need,
        self_motivation=self_motivation,
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("1"),
        reasoning_summary="当前不允许主动交流",
    )
