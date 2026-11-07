from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind, TopicTransition

FALLBACK_USER_TEXT = "我暂时无法完成这次回复。"
RECENT_MESSAGE_LIMIT = 10

_INTENSITY_WORDS = {
    "none": 0.0,
    "no": 0.0,
    "low": 0.3,
    "weak": 0.3,
    "medium": 0.5,
    "mid": 0.5,
    "moderate": 0.5,
    "normal": 0.5,
    "high": 0.8,
    "strong": 0.85,
    "very_high": 1.0,
    "max": 1.0,
}

# 模型常把关系动机写成近义标签；映射到已有 SelfMotivationKind。
_KIND_ALIASES = {
    "maintain_connection": SelfMotivationKind.SEEK_CONNECTION,
    "keep_connection": SelfMotivationKind.SEEK_CONNECTION,
    "connection": SelfMotivationKind.SEEK_CONNECTION,
    "reassurance": SelfMotivationKind.SHOW_CARE,
    "reassure": SelfMotivationKind.SHOW_CARE,
    "comfort": SelfMotivationKind.SHOW_CARE,
    "care": SelfMotivationKind.SHOW_CARE,
    "check_in": SelfMotivationKind.SHOW_CARE,
    "presence": SelfMotivationKind.SEEK_CONNECTION,
    "greeting": SelfMotivationKind.SEEK_CONNECTION,
    "affection": SelfMotivationKind.EXPRESS_EMOTION,
    "emotion": SelfMotivationKind.EXPRESS_EMOTION,
    "interest": SelfMotivationKind.SHARE_INTEREST,
    "thought": SelfMotivationKind.SHARE_THOUGHT,
    "opinion": SelfMotivationKind.EXPRESS_OPINION,
    "attention": SelfMotivationKind.SEEK_ATTENTION,
    "play": SelfMotivationKind.PLAYFUL_INTERACTION,
    "memory": SelfMotivationKind.RECALL_MEMORY,
    "topic": SelfMotivationKind.CONTINUE_TOPIC,
    "assert": SelfMotivationKind.ASSERT_STANCE,
    "assert_stance": SelfMotivationKind.ASSERT_STANCE,
    "hold_position": SelfMotivationKind.ASSERT_STANCE,
    "stand_ground": SelfMotivationKind.ASSERT_STANCE,
    "grievance": SelfMotivationKind.EXPRESS_GRIEVANCE,
    "express_grievance": SelfMotivationKind.EXPRESS_GRIEVANCE,
    "complaint": SelfMotivationKind.EXPRESS_GRIEVANCE,
    "blame": SelfMotivationKind.EXPRESS_GRIEVANCE,
    "resentment": SelfMotivationKind.EXPRESS_GRIEVANCE,
    "acknowledgment": SelfMotivationKind.SEEK_ACKNOWLEDGMENT,
    "seek_acknowledgment": SelfMotivationKind.SEEK_ACKNOWLEDGMENT,
    "want_understanding": SelfMotivationKind.SEEK_ACKNOWLEDGMENT,
    "need_explanation": SelfMotivationKind.SEEK_ACKNOWLEDGMENT,
}


def _coerce_text_part(value: object) -> object:
    """兴趣/观点/表达欲必须是文字；模型常返回 null/false/数字。"""
    if value is None or value is False:
        return "没有"
    if value is True:
        return "有"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value) <= 0:
            return "没有"
        return "有一点想表达"
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_intensity(value: object) -> object:
    if value is None or value is False:
        return 0.0
    if value is True:
        return 1.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number < 0:
            return 0.0
        if number > 1:
            return 1.0
        return number
    if isinstance(value, str):
        stripped = value.strip().lower().replace("-", "_").replace(" ", "_")
        if not stripped:
            return 0.0
        if stripped in _INTENSITY_WORDS:
            return _INTENSITY_WORDS[stripped]
        try:
            number = float(stripped)
        except ValueError:
            return value
        if number < 0:
            return 0.0
        if number > 1:
            return 1.0
        return number
    return value


def _coerce_motivation_kind(value: object) -> object:
    if value is None or value == "":
        return SelfMotivationKind.NONE
    if isinstance(value, SelfMotivationKind):
        return value
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return SelfMotivationKind.NONE
    try:
        return SelfMotivationKind(text)
    except ValueError:
        pass
    if text in _KIND_ALIASES:
        return _KIND_ALIASES[text]
    for kind in SelfMotivationKind:
        if text in kind.value or kind.value in text:
            return kind
    return SelfMotivationKind.NONE


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

    kind: SelfMotivationKind = SelfMotivationKind.NONE
    interest: str = Field(min_length=1, max_length=200)
    viewpoint: str = Field(min_length=1, max_length=200)
    desire_to_express: str = Field(min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=200)

    @field_validator("interest", "viewpoint", "desire_to_express", mode="before")
    @classmethod
    def missing_means_none(cls, value: object) -> object:
        return _coerce_text_part(value)

    @field_validator("interest", "viewpoint", "desire_to_express")
    @classmethod
    def strip_part(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("kind", mode="before")
    @classmethod
    def missing_kind_is_none(cls, value: object) -> object:
        return _coerce_motivation_kind(value)

    @field_validator("source", "reason")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class EmotionalMotivation(BaseModel):
    """由当前情绪驱动的表达动机。可以为空，不要求每轮都有。"""

    model_config = ConfigDict(extra="forbid")

    emotion: str = Field(min_length=1, max_length=32)
    intensity: float = Field(ge=0, le=1)

    @field_validator("emotion", mode="before")
    @classmethod
    def coerce_emotion(cls, value: object) -> object:
        if value is None:
            return "平静"
        return value

    @field_validator("emotion")
    @classmethod
    def strip_emotion(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("intensity", mode="before")
    @classmethod
    def coerce_intensity(cls, value: object) -> object:
        return _coerce_intensity(value)


class RelationshipMotivation(BaseModel):
    """由依恋/关系需求驱动的动机。不等于控制用户。"""

    model_config = ConfigDict(extra="forbid")

    kind: SelfMotivationKind
    intensity: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, max_length=200)

    @field_validator("kind", mode="before")
    @classmethod
    def missing_kind_is_none(cls, value: object) -> object:
        return _coerce_motivation_kind(value)

    @field_validator("intensity", mode="before")
    @classmethod
    def coerce_intensity(cls, value: object) -> object:
        return _coerce_intensity(value)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class FactCheckResult(BaseModel):
    """决策前的事实核对。推断和低置信度观察不能当作冲突依据。"""

    model_config = ConfigDict(extra="forbid")

    has_conflict: bool = False
    conflict_summary: str | None = Field(default=None, max_length=200)
    should_correct: bool = False

    @field_validator("conflict_summary")
    @classmethod
    def strip_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def conflict_requires_summary(self) -> "FactCheckResult":
        if self.has_conflict:
            if not self.conflict_summary:
                raise ValueError("事实冲突必须写明冲突内容")
            if not self.should_correct:
                raise ValueError("已确认的事实冲突必须纠正，不能顺着接")
        elif self.conflict_summary is not None or self.should_correct:
            raise ValueError("没有事实冲突时不能标记纠正")
        return self


class ModelDecisionSuggestion(BaseModel):
    """模型只提供建议。是否发送由 Python 决定。"""

    model_config = ConfigDict(extra="forbid")

    should_send: bool
    primary_action: DialogueAction
    secondary_actions: list[DialogueAction] = Field(default_factory=list)
    motivation: DecisionMotivation
    user_need: UserNeed
    self_motivation: SelfMotivation
    emotional_motivation: EmotionalMotivation | None = None
    relationship_motivation: RelationshipMotivation | None = None
    topic: DecisionTopic = Field(default_factory=DecisionTopic)
    fact_check: FactCheckResult = Field(default_factory=FactCheckResult)
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
        relationship_reason = ""
        if self.relationship_motivation is not None:
            relationship_reason = self.relationship_motivation.reason or ""
        blob = " ".join(
            [
                self.motivation.primary,
                self.motivation.summary or "",
                self.reasoning_summary,
                self.user_need.summary,
                self.self_motivation.interest,
                self.self_motivation.viewpoint,
                self.self_motivation.desire_to_express,
                self.self_motivation.reason or "",
                relationship_reason,
                self.fact_check.conflict_summary or "",
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
            kind=SelfMotivationKind.NONE,
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
