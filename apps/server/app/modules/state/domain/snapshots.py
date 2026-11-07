from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.state.domain.emotion import default_levels, normalize_levels
from app.modules.state.domain.enums import InteractionEnergy, InteractionMode, MotivationKind


class EmotionState(BaseModel):
    """情绪快照。十维 levels 是 V1 主状态；jealousy 等遗留字段并行保留。"""

    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=32)
    secondary: list[str] = Field(default_factory=list)
    intensity: float = Field(ge=0, le=1)
    valence: float = Field(ge=0, le=1)
    arousal: float = Field(ge=0, le=1)
    jealousy: float = Field(default=0, ge=0, le=1)
    possessiveness: float = Field(default=0, ge=0, le=1)
    emotional_tension: float = Field(default=0, ge=0, le=1)
    triggers: list[str] = Field(default_factory=list)
    cause_summary: str = Field(min_length=1)
    levels: dict[str, float] = Field(default_factory=default_levels)
    updated_at: datetime

    @field_validator("primary", "cause_summary")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("secondary")
    @classmethod
    def clean_secondary(cls, value: list[str]) -> list[str]:
        return _unique_texts(value)

    @field_validator("triggers")
    @classmethod
    def clean_triggers(cls, value: list[str]) -> list[str]:
        return _unique_texts(value, max_length=64)

    @model_validator(mode="after")
    def normalize_emotion_levels(self) -> "EmotionState":
        levels = normalize_levels(self.levels)
        # 依恋路径可能只改了 0-1 的 jealousy；回写到十维。
        level_jealousy = levels["jealousy"] / 100.0
        if abs(self.jealousy - level_jealousy) > 0.0005:
            if self.jealousy > level_jealousy:
                levels["jealousy"] = round(self.jealousy * 100.0, 2)
            else:
                object.__setattr__(self, "jealousy", round(levels["jealousy"] / 100.0, 3))
        object.__setattr__(self, "levels", levels)
        return self


class EmotionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=32)
    secondary: list[str] = Field(default_factory=list)
    intensity: float = Field(ge=0, le=1)
    valence: float = Field(ge=0, le=1)
    arousal: float = Field(ge=0, le=1)
    jealousy: float = Field(default=0, ge=0, le=1)
    possessiveness: float = Field(default=0, ge=0, le=1)
    emotional_tension: float = Field(default=0, ge=0, le=1)
    triggers: list[str] = Field(default_factory=list)
    cause_summary: str = Field(min_length=1)
    levels: dict[str, float] = Field(default_factory=default_levels)

    @field_validator("primary", "cause_summary")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("secondary")
    @classmethod
    def clean_secondary(cls, value: list[str]) -> list[str]:
        return _unique_texts(value)

    @field_validator("triggers")
    @classmethod
    def clean_triggers(cls, value: list[str]) -> list[str]:
        return _unique_texts(value, max_length=64)

    @model_validator(mode="after")
    def normalize_emotion_levels(self) -> "EmotionInput":
        levels = normalize_levels(self.levels)
        level_jealousy = levels["jealousy"] / 100.0
        if abs(self.jealousy - level_jealousy) > 0.0005:
            if self.jealousy > level_jealousy:
                levels["jealousy"] = round(self.jealousy * 100.0, 2)
            else:
                object.__setattr__(self, "jealousy", round(levels["jealousy"] / 100.0, 3))
        object.__setattr__(self, "levels", levels)
        return self


class RelationshipState(BaseModel):
    """关系与依恋状态。数值只供内部使用，不是用户可见的好感度。"""

    model_config = ConfigDict(extra="forbid")

    closeness: float = Field(ge=0, le=1)
    trust: float = Field(ge=0, le=1)
    attachment: float = Field(ge=0, le=1)
    care: float = Field(ge=0, le=1)
    current_tension: float = Field(ge=0, le=1)
    attachment_strength: float = Field(default=0, ge=0, le=1)
    emotional_reliance: float = Field(default=0, ge=0, le=1)
    relationship_security: float = Field(default=0, ge=0, le=1)
    perceived_specialness: float = Field(default=0, ge=0, le=1)
    separation_sensitivity: float = Field(default=0, ge=0, le=1)
    reassurance_satisfaction: float = Field(default=0, ge=0, le=1)
    closeness_desire: float = Field(default=0, ge=0, le=1)
    exclusivity_need: float = Field(default=0, ge=0, le=1)
    summary: str = Field(min_length=1)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class InteractionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: InteractionMode
    proactive_allowed: bool
    waiting_for_user: bool
    energy: InteractionEnergy = InteractionEnergy.NORMAL
    last_user_response_at: datetime | None = None
    last_companion_message_at: datetime | None = None
    consecutive_unanswered_messages: int = Field(ge=0)
    consecutive_quiet_turns: int = Field(default=0, ge=0)
    quiet_until: datetime | None = None


class MotivationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: MotivationKind
    secondary: list[MotivationKind] = Field(default_factory=list)
    intensity: float = Field(ge=0, le=1)
    target: str | None = Field(default=None, max_length=64)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("target")
    @classmethod
    def strip_target(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("secondary")
    @classmethod
    def unique_secondary(cls, value: list[MotivationKind], info: object) -> list[MotivationKind]:
        primary = getattr(info, "data", {}).get("primary")
        if len(value) != len(set(value)) or primary in value:
            raise ValueError("动机不能重复")
        return value


def initial_snapshots(now: datetime) -> dict[str, BaseModel]:
    """初始化只记录尚未形成的内部状态，不写入关系经历或主动交流许可。"""
    return {
        "emotion": EmotionState(
            primary="calm",
            secondary=[],
            intensity=0,
            valence=0,
            arousal=0,
            jealousy=0,
            possessiveness=0,
            emotional_tension=0,
            triggers=[],
            cause_summary="状态初始化",
            levels=default_levels(),
            updated_at=now,
        ),
        "relationship": RelationshipState(
            closeness=0,
            trust=0,
            attachment=0,
            care=0,
            current_tension=0,
            attachment_strength=0,
            emotional_reliance=0,
            relationship_security=0,
            perceived_specialness=0,
            separation_sensitivity=0,
            reassurance_satisfaction=0,
            closeness_desire=0,
            exclusivity_need=0,
            summary="状态初始化",
        ),
        "interaction": InteractionState(
            mode=InteractionMode.AVAILABLE,
            proactive_allowed=True,
            waiting_for_user=False,
            energy=InteractionEnergy.NORMAL,
            consecutive_unanswered_messages=0,
            consecutive_quiet_turns=0,
        ),
        "motivation": MotivationState(
            primary=MotivationKind.REST,
            secondary=[],
            intensity=0,
            target=None,
            reason="状态初始化",
        ),
    }


def dump_snapshot(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="json")


def _unique_texts(value: list[str], *, max_length: int = 32) -> list[str]:
    cleaned: list[str] = []
    for item in value:
        text = item.strip()
        if not text:
            raise ValueError("不能为空")
        if len(text) > max_length:
            raise ValueError("过长")
        if text in cleaned:
            raise ValueError("不能重复")
        cleaned.append(text)
    return cleaned
