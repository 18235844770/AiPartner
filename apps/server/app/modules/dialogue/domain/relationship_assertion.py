"""关系自我主张决策因子。参数与情绪共同影响倾向，不直接决定行为。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.modules.persona.domain.archive import (
    RelationshipSelfAssertion,
    TendencyLevel,
    default_self_assertion,
    forgiveness_half_life_multipliers,
)
from app.modules.state.domain.emotion import normalize_levels

# 再导出，供对话侧测试与调用保持稳定。
__all__ = (
    "RelationshipAssertionFactor",
    "build_relationship_assertion",
    "confrontation_persona_factor",
    "forgiveness_half_life_multipliers",
    "resentment_persona_factor",
    "tendency_weight",
    "user_message_has_friction",
)

_LEVEL_WEIGHT = {
    TendencyLevel.LOW: 0.35,
    TendencyLevel.MEDIUM: 0.65,
    TendencyLevel.HIGH: 1.0,
}

_ACTIVE = 15.0
_HIGH = 35.0

_FRICTION_CUES = (
    "你想多了",
    "别矫情",
    "太大惊小怪",
    "没必要生气",
    "你太敏感",
    "你多心了",
    "没事的吧",
    "你误会了",
    "别瞎想",
    "你不懂",
    "随便你",
    "爱怎样怎样",
    "少管我",
    "关你什么事",
    "别抱怨",
    "别委屈",
    "你又来了",
    "烦不烦",
    "够了",
    "闭嘴",
)


@dataclass(frozen=True)
class RelationshipAssertionFactor:
    stance_pressure: float
    confrontation_bias: float
    intimacy_dampen: float
    repair_openness: float
    stance_hint: str

    def as_context(self) -> dict[str, object]:
        return {
            "stance_pressure": self.stance_pressure,
            "confrontation_bias": self.confrontation_bias,
            "intimacy_dampen": self.intimacy_dampen,
            "repair_openness": self.repair_openness,
            "stance_hint": self.stance_hint,
        }


def tendency_weight(level: TendencyLevel) -> float:
    return _LEVEL_WEIGHT[level]


def build_relationship_assertion(
    self_assertion: RelationshipSelfAssertion | None,
    levels: Mapping[str, float] | None,
) -> RelationshipAssertionFactor:
    profile = self_assertion or default_self_assertion()
    normalized = normalize_levels(levels)
    anger = normalized["anger"]
    hurt = normalized["hurt"]
    sadness = normalized["sadness"]
    negative = max(anger, hurt, sadness)
    negative_unit = min(1.0, negative / 100.0)
    assert_w = tendency_weight(profile.assertiveness)
    confront_w = tendency_weight(profile.confrontation_tendency)
    resent_w = tendency_weight(profile.resentment_tendency)
    forgive_w = tendency_weight(profile.forgiveness_tendency)

    stance_pressure = round(min(1.0, assert_w * (0.35 + 0.65 * negative_unit)), 3)
    confrontation_bias = round(min(1.0, confront_w * (0.3 + 0.7 * max(anger, hurt) / 100.0)), 3)
    intimacy_dampen = round(min(1.0, (0.55 * hurt + 0.45 * anger) / 100.0 * (0.5 + 0.5 * resent_w)), 3)
    repair_openness = round(
        min(1.0, forgive_w * (1.0 - 0.7 * min(1.0, max(anger, hurt) / 100.0))),
        3,
    )
    return RelationshipAssertionFactor(
        stance_pressure=stance_pressure,
        confrontation_bias=confrontation_bias,
        intimacy_dampen=intimacy_dampen,
        repair_openness=repair_openness,
        stance_hint=_hint(anger=anger, hurt=hurt, sadness=sadness, factor_pressure=stance_pressure),
    )


def user_message_has_friction(text: str | None) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return any(cue.lower() in lowered for cue in _FRICTION_CUES)


def resentment_persona_factor(level: TendencyLevel) -> float:
    return {TendencyLevel.LOW: 0.7, TendencyLevel.MEDIUM: 1.0, TendencyLevel.HIGH: 1.35}[level]


def confrontation_persona_factor(level: TendencyLevel) -> float:
    return {TendencyLevel.LOW: 0.75, TendencyLevel.MEDIUM: 1.0, TendencyLevel.HIGH: 1.3}[level]


def _hint(*, anger: float, hurt: float, sadness: float, factor_pressure: float) -> str:
    pieces: list[str] = []
    if anger >= _HIGH:
        pieces.append("愤怒较高：可更直接表达不满，也可拒绝继续当前话题")
    elif anger >= _ACTIVE:
        pieces.append("有怒意：允许批评或责备，不要只安抚")
    if hurt >= _HIGH:
        pieces.append("委屈较高：减少主动亲密表达，可希望对方解释")
    elif hurt >= _ACTIVE:
        pieces.append("有委屈：可以说出不适，不要立刻装作没事")
    if sadness >= _HIGH and hurt < _HIGH:
        pieces.append("难过持续：主动交流意愿可下降，但不必迎合")
    if factor_pressure >= 0.55:
        pieces.append("可坚持自己的关系立场；用户否定感受时不要立刻认错或妥协")
    if not pieces:
        pieces.append("关系主张保持自然：需要时可表达不满，不必每轮表演冲突")
    return "；".join(pieces)
