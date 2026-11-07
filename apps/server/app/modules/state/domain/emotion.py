"""Emotion V1：十维独立情绪、事件驱动增量、指数衰减。

Python 拥有最终数值裁定权；LLM 只可建议事件与强度，不可直接写库。
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMOTION_KEYS: tuple[str, ...] = (
    "joy",
    "affection",
    "longing",
    "comfort",
    "excitement",
    "sadness",
    "anxiety",
    "jealousy",
    "anger",
    "hurt",
)

EMOTION_LABELS: dict[str, str] = {
    "joy": "开心",
    "affection": "亲密",
    "longing": "想念",
    "comfort": "安心",
    "excitement": "兴奋",
    "sadness": "难过",
    "anxiety": "不安",
    "jealousy": "嫉妒",
    "anger": "愤怒",
    "hurt": "委屈",
    "calm": "平静",
}

# 回合动作带来的可读情绪名（中文），避免调试页出现 attentive 等英文。
ACTION_EMOTION_LABELS: dict[str, str] = {
    "attentive": "专注",
    "engaged": "投入",
    "curious": "好奇",
    "moved": "触动",
    "calm": "平静",
    "happy": "开心",
}


def emotion_display_name(key: str) -> str:
    if key in EMOTION_LABELS:
        return EMOTION_LABELS[key]
    if key in ACTION_EMOTION_LABELS:
        return ACTION_EMOTION_LABELS[key]
    return key


def primary_from_levels(levels: Mapping[str, float], *, fallback: str = "平静") -> str:
    dominant = dominant_emotion(levels)
    if dominant == "calm":
        return fallback if fallback else "平静"
    return emotion_display_name(dominant)

# 半衰期（小时）。文档初始建议，后续可调。
HALF_LIFE_HOURS: dict[str, float] = {
    "joy": 6,
    "affection": 72,
    "longing": 36,
    "comfort": 72,
    "excitement": 3,
    "sadness": 24,
    "anxiety": 18,
    "jealousy": 18,
    "anger": 12,
    "hurt": 30,
}

BASELINE_LEVEL = 0.0
LEVEL_MIN = 0.0
LEVEL_MAX = 100.0
_ACTIVE_THRESHOLD = 15.0
_HUNDREDTH = Decimal("0.01")


class EmotionEventKind(StrEnum):
    POSITIVE_INTERACTION = "positive_interaction"
    AFFECTION_EXPRESSION = "affection_expression"
    ATTENTION_RECEIVED = "attention_received"
    MEANINGFUL_CONVERSATION = "meaningful_conversation"
    SHARED_INTEREST = "shared_interest"
    USER_ABSENCE = "user_absence"
    REUNION = "reunion"
    REJECTION = "rejection"
    RELATIONSHIP_THREAT = "relationship_threat"
    CONFLICT = "conflict"
    BOUNDARY_VIOLATION = "boundary_violation"
    DISAPPOINTMENT = "disappointment"
    RECONCILIATION = "reconciliation"
    ATTENTIVE_LISTEN = "attentive_listen"
    CURIOSITY = "curiosity"
    QUIET_REST = "quiet_rest"


# 事件基础变化量 B（0-100 刻度上的增量）。负值表示下降。
EVENT_BASE_DELTAS: dict[EmotionEventKind, dict[str, float]] = {
    EmotionEventKind.POSITIVE_INTERACTION: {"joy": 8, "affection": 4},
    EmotionEventKind.AFFECTION_EXPRESSION: {"affection": 10, "joy": 6, "comfort": 5},
    EmotionEventKind.ATTENTION_RECEIVED: {"joy": 6, "comfort": 6, "affection": 4},
    EmotionEventKind.MEANINGFUL_CONVERSATION: {"affection": 6, "comfort": 5},
    EmotionEventKind.SHARED_INTEREST: {"joy": 7, "excitement": 8},
    EmotionEventKind.USER_ABSENCE: {"longing": 10, "anxiety": 7},
    EmotionEventKind.REUNION: {"joy": 10, "comfort": 8, "longing": -12},
    EmotionEventKind.REJECTION: {"sadness": 8, "anxiety": 5, "hurt": 7},
    # 关系威胁：可感知的在意，但默认不拉满成强烈嫉妒。
    EmotionEventKind.RELATIONSHIP_THREAT: {"jealousy": 18, "anxiety": 10},
    EmotionEventKind.CONFLICT: {"anger": 8, "sadness": 5, "hurt": 5},
    EmotionEventKind.BOUNDARY_VIOLATION: {"anger": 10, "anxiety": 6},
    EmotionEventKind.DISAPPOINTMENT: {"sadness": 7, "hurt": 6},
    EmotionEventKind.RECONCILIATION: {"comfort": 8, "anger": -8, "sadness": -5, "hurt": -4},
    EmotionEventKind.ATTENTIVE_LISTEN: {"comfort": 3, "affection": 2},
    EmotionEventKind.CURIOSITY: {"excitement": 4, "joy": 2},
    EmotionEventKind.QUIET_REST: {"excitement": -4, "anxiety": -2},
}


class EmotionDeltaEvent(BaseModel):
    """一次可核对的情绪事件建议。最终数值由 Python 计算。"""

    model_config = ConfigDict(extra="forbid")

    kind: EmotionEventKind
    intensity: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    persona_factor: float = Field(default=1.0, ge=0.2, le=2.0)
    reason: str = Field(min_length=1, max_length=200)
    source_message_id: str | None = None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


def default_levels() -> dict[str, float]:
    return {key: BASELINE_LEVEL for key in EMOTION_KEYS}


def normalize_levels(raw: Mapping[str, object] | None) -> dict[str, float]:
    levels = default_levels()
    if not raw:
        return levels
    for key in EMOTION_KEYS:
        value = raw.get(key, BASELINE_LEVEL)
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            number = BASELINE_LEVEL
        levels[key] = clamp_level(number)
    return levels


def clamp_level(value: float) -> float:
    if value < LEVEL_MIN:
        return LEVEL_MIN
    if value > LEVEL_MAX:
        return LEVEL_MAX
    return float(Decimal(str(value)).quantize(_HUNDREDTH, rounding=ROUND_HALF_UP))


def compute_event_deltas(
    kind: EmotionEventKind,
    *,
    intensity: float = 0.5,
    confidence: float = 1.0,
    persona_factor: float = 1.0,
) -> dict[str, float]:
    """ΔE = B × I × P × C。"""
    base = EVENT_BASE_DELTAS.get(kind, {})
    result: dict[str, float] = {}
    scale = max(0.0, intensity) * max(0.0, confidence) * max(0.0, persona_factor)
    for key, amount in base.items():
        if key not in EMOTION_KEYS:
            continue
        result[key] = clamp_level(amount * scale) if amount >= 0 else -clamp_level(abs(amount) * scale)
    return result


def apply_deltas(levels: Mapping[str, float], deltas: Mapping[str, float]) -> dict[str, float]:
    next_levels = normalize_levels(levels)
    for key, delta in deltas.items():
        if key not in EMOTION_KEYS:
            continue
        next_levels[key] = clamp_level(next_levels[key] + float(delta))
    return next_levels


def apply_events(
    levels: Mapping[str, float],
    events: list[EmotionDeltaEvent],
) -> tuple[dict[str, float], dict[str, float]]:
    """应用事件列表，返回 (after, merged_deltas)。按 source_message_id+kind 去重。"""
    seen: set[tuple[str | None, str]] = set()
    merged: dict[str, float] = {key: 0.0 for key in EMOTION_KEYS}
    for event in events:
        fingerprint = (event.source_message_id, event.kind.value)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        piece = compute_event_deltas(
            event.kind,
            intensity=event.intensity,
            confidence=event.confidence,
            persona_factor=event.persona_factor,
        )
        for key, delta in piece.items():
            merged[key] = merged.get(key, 0.0) + delta
    cleaned = {key: clamp_level(value) if value >= 0 else -clamp_level(abs(value)) for key, value in merged.items() if abs(value) > 0}
    return apply_deltas(levels, cleaned), cleaned


def decay_levels(
    levels: Mapping[str, float],
    elapsed: timedelta,
    *,
    toward: float = BASELINE_LEVEL,
    half_life_multipliers: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """E_t = toward + (E_0 - toward) * 2^(-Δt / T)。"""
    seconds = max(0.0, elapsed.total_seconds())
    if seconds <= 0:
        return normalize_levels(levels)
    multipliers = half_life_multipliers or {}
    result = default_levels()
    for key in EMOTION_KEYS:
        current = float(normalize_levels(levels)[key])
        scale = float(multipliers.get(key, 1.0))
        if scale <= 0:
            scale = 1.0
        half_life = HALF_LIFE_HOURS[key] * 3600.0 * scale
        if half_life <= 0:
            result[key] = clamp_level(toward)
            continue
        factor = 0.5 ** (seconds / half_life)
        result[key] = clamp_level(toward + (current - toward) * factor)
    return result


def dominant_emotion(levels: Mapping[str, float]) -> str:
    normalized = normalize_levels(levels)
    key = max(EMOTION_KEYS, key=lambda item: normalized[item])
    if normalized[key] < _ACTIVE_THRESHOLD:
        return "calm"
    return key


def derived_intensity(levels: Mapping[str, float]) -> float:
    normalized = normalize_levels(levels)
    peak = max(normalized.values()) if normalized else 0.0
    return clamp_unit(peak / LEVEL_MAX)


def derived_valence(levels: Mapping[str, float]) -> float:
    normalized = normalize_levels(levels)
    positive = normalized["joy"] + normalized["affection"] + normalized["comfort"] + normalized["excitement"]
    negative = normalized["sadness"] + normalized["anxiety"] + normalized["jealousy"] + normalized["anger"] + normalized["hurt"]
    total = positive + negative
    if total <= 0:
        return 0.0
    return clamp_unit(positive / total)


def derived_arousal(levels: Mapping[str, float]) -> float:
    normalized = normalize_levels(levels)
    aroused = (
        normalized["excitement"]
        + normalized["anxiety"]
        + normalized["anger"]
        + normalized["jealousy"]
        + normalized["longing"] * 0.5
    )
    return clamp_unit(aroused / (LEVEL_MAX * 3.5))


def sync_legacy_from_levels(levels: Mapping[str, float]) -> dict[str, float | str | list[str]]:
    normalized = normalize_levels(levels)
    primary_key = dominant_emotion(normalized)
    secondary_keys = [
        key
        for key in sorted(EMOTION_KEYS, key=lambda item: normalized[item], reverse=True)
        if key != primary_key and normalized[key] >= _ACTIVE_THRESHOLD
    ][:3]
    return {
        "primary": emotion_display_name(primary_key),
        "secondary": [emotion_display_name(key) for key in secondary_keys],
        "intensity": derived_intensity(normalized),
        "valence": derived_valence(normalized),
        "arousal": derived_arousal(normalized),
        "jealousy": clamp_unit(normalized["jealousy"] / LEVEL_MAX),
    }


def levels_summary(levels: Mapping[str, float]) -> dict[str, object]:
    """决策/表达用压缩摘要。表达侧应避免把数值念给用户。"""
    normalized = normalize_levels(levels)
    ranked = sorted(EMOTION_KEYS, key=lambda key: normalized[key], reverse=True)
    active = []
    for key in ranked:
        value = normalized[key]
        if value < _ACTIVE_THRESHOLD:
            continue
        active.append(
            {
                "key": key,
                "label": EMOTION_LABELS[key],
                "band": _band(value),
            }
        )
        if len(active) >= 4:
            break
    dominant = dominant_emotion(normalized)
    return {
        "dominant": dominant,
        "dominant_label": "平静" if dominant == "calm" else EMOTION_LABELS.get(dominant, dominant),
        "active": active,
    }


def clamp_unit(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _band(value: float) -> str:
    if value >= 70:
        return "high"
    if value >= 40:
        return "medium"
    return "low"
