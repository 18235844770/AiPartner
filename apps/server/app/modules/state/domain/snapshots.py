from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.state.domain.enums import InteractionMode, MotivationKind


class EmotionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=32)
    secondary: list[str] = Field(default_factory=list)
    intensity: float = Field(ge=0, le=1)
    valence: float = Field(ge=0, le=1)
    arousal: float = Field(ge=0, le=1)
    cause_summary: str = Field(min_length=1)
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


class EmotionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=32)
    secondary: list[str] = Field(default_factory=list)
    intensity: float = Field(ge=0, le=1)
    valence: float = Field(ge=0, le=1)
    arousal: float = Field(ge=0, le=1)
    cause_summary: str = Field(min_length=1)

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


class RelationshipState(BaseModel):
    """关系数值只供内部状态使用，不是用户可见的好感度。"""

    model_config = ConfigDict(extra="forbid")

    closeness: float = Field(ge=0, le=1)
    trust: float = Field(ge=0, le=1)
    attachment: float = Field(ge=0, le=1)
    care: float = Field(ge=0, le=1)
    current_tension: float = Field(ge=0, le=1)
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
    last_user_response_at: datetime | None = None
    last_companion_message_at: datetime | None = None
    consecutive_unanswered_messages: int = Field(ge=0)
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
            cause_summary="状态初始化",
            updated_at=now,
        ),
        "relationship": RelationshipState(
            closeness=0,
            trust=0,
            attachment=0,
            care=0,
            current_tension=0,
            summary="状态初始化",
        ),
        "interaction": InteractionState(
            mode=InteractionMode.AVAILABLE,
            proactive_allowed=False,
            waiting_for_user=False,
            consecutive_unanswered_messages=0,
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


def _unique_texts(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in value:
        text = item.strip()
        if not text:
            raise ValueError("不能为空")
        if len(text) > 32:
            raise ValueError("过长")
        if text in cleaned:
            raise ValueError("不能重复")
        cleaned.append(text)
    return cleaned
