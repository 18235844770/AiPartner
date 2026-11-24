"""表情目录。按数据加载，不写入人格版本。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.modules.persona.domain.enums import MbtiType

_DATA = Path(__file__).resolve().parents[1] / "data" / "expression_marks.json"
_KAOMOJI_GROUP_INTENSITY = {
    "smile": "低",
    "shy": "中",
    "pout": "中高",
    "upset": "高",
    "confused": "中",
    "playful": "中高",
    "intimate": "中",
    "tired": "低",
}


class ExpressionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mark: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    intensity: str = "中"
    scenes: list[str] = Field(default_factory=list)
    group_id: str = ""
    kind: str = "emoji"


class ExpressionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    items: list[ExpressionItem] = Field(min_length=1)


class EmotionMarkRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emotion: str = Field(min_length=1)
    label: str = Field(min_length=1)
    recommended: list[str] = Field(min_length=1)
    discouraged: list[str] = Field(default_factory=list)
    discouraged_note: str | None = None


class MarkFrequency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_emoji_per_message: int = Field(ge=0, le=2)
    max_kaomoji_per_message: int = Field(ge=0, le=1)
    emoji_probability: dict[str, float]
    kaomoji_probability: dict[str, float]
    strong_emotion_probability: dict[str, float]
    avoid_same_mark_on_consecutive_messages: bool = True
    serious_topic: str = "low"
    factual_answer: str = "low"


class PersonaMarkStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mbti: str
    style: str = Field(min_length=1)
    emoji_rate: float = Field(ge=0, le=1)
    kaomoji_rate: float = Field(ge=0, le=1)
    max_intensity: str = Field(min_length=1)
    preferred_groups: list[str] = Field(default_factory=list)


class ExpressionCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emoji: list[ExpressionGroup]
    kaomoji_groups: list[ExpressionGroup]
    frequency: MarkFrequency
    emotion_mapping: list[EmotionMarkRule]
    persona_styles: dict[str, PersonaMarkStyle]
    by_mark: dict[str, ExpressionItem]


def _attach(group: ExpressionGroup, kind: str, intensity: str | None = None) -> ExpressionGroup:
    items: list[ExpressionItem] = []
    for item in group.items:
        items.append(
            item.model_copy(
                update={
                    "group_id": group.id,
                    "kind": kind,
                    "intensity": intensity or item.intensity,
                }
            )
        )
    return group.model_copy(update={"items": items})


@lru_cache
def load_expression_catalog() -> ExpressionCatalog:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("expression_marks 必须是对象")
    emoji = [_attach(ExpressionGroup.model_validate(item), "emoji") for item in raw["emoji"]]
    kaomoji_raw = raw["kaomoji"]["groups"]
    kaomoji = [
        _attach(
            ExpressionGroup.model_validate(item),
            "kaomoji",
            _KAOMOJI_GROUP_INTENSITY.get(str(item.get("id")), "中"),
        )
        for item in kaomoji_raw
    ]
    rules = raw["rules"]
    styles = {
        item["mbti"]: PersonaMarkStyle.model_validate(item) for item in rules["persona_styles"]
    }
    expected = {item.value for item in MbtiType}
    if set(styles) != expected:
        raise ValueError("expression_marks 的人格倾向必须覆盖六种 MBTI")
    by_mark: dict[str, ExpressionItem] = {}
    for group in [*emoji, *kaomoji]:
        for item in group.items:
            by_mark.setdefault(item.mark, item)
    return ExpressionCatalog(
        emoji=emoji,
        kaomoji_groups=kaomoji,
        frequency=MarkFrequency.model_validate(rules["frequency"]),
        emotion_mapping=[EmotionMarkRule.model_validate(item) for item in rules["emotion_mapping"]],
        persona_styles=styles,
        by_mark=by_mark,
    )
