"""临时情绪会过去，到期的安静时段会结束。缺席时可按关系倾向微调想念/不安与关系状态。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.modules.state.domain.emotion import (
    EMOTION_KEYS,
    EmotionEventKind,
    apply_deltas,
    clamp_level,
    compute_event_deltas,
    decay_levels,
    emotion_display_name,
    normalize_levels,
    sync_legacy_from_levels,
)
from app.modules.state.domain.enums import InteractionMode
from app.modules.state.domain.snapshots import EmotionInput, EmotionState, InteractionState, RelationshipState

_MIN_ELAPSED = timedelta(minutes=1)
_ABSENCE_GAP = timedelta(hours=18)
_ABSENCE_LONGING_CAP = 40.0
SETTLED_CAUSE = "临时情绪已经过去"
EMOTION_REASON = "临时情绪随时间衰减"
ABSENCE_REASON = "用户一段时间没有交流，想念上升"
ABSENCE_RELATIONSHIP_REASON = "缺席期间关系需求随倾向变化"
QUIET_REASON = "安静时段已经结束"
# 兼容旧测试与调度窗口描述：约等于开心的半衰期。
EMOTION_DECAY_WINDOW = timedelta(hours=6)

_TENDENCY_WEIGHT = {
    "low": 0.55,
    "medium": 1.0,
    "high": 1.45,
}
_THOUSANDTH = Decimal("0.001")


@dataclass(frozen=True)
class AbsenceDispositionFactors:
    """缺席维护用的倾向系数。1.0 为中等基线。"""

    longing_factor: float = 1.0
    anxiety_factor: float = 1.0
    separation_factor: float = 1.0
    dependency_factor: float = 1.0
    reassurance_factor: float = 1.0


@dataclass(frozen=True)
class MaintenancePlan:
    emotion: EmotionInput | None = None
    interaction: InteractionState | None = None
    relationship: RelationshipState | None = None
    emotion_reason: str | None = None
    relationship_reason: str | None = None

    @property
    def reason(self) -> str | None:
        parts: list[str] = []
        if self.emotion is not None:
            parts.append(self.emotion_reason or EMOTION_REASON)
        if self.relationship is not None:
            parts.append(self.relationship_reason or ABSENCE_RELATIONSHIP_REASON)
        if self.interaction is not None:
            parts.append(QUIET_REASON)
        if not parts:
            return None
        return "；".join(parts)


def factors_from_disposition(raw: Mapping[str, object] | None) -> AbsenceDispositionFactors:
    """从 attachment_disposition 字典构造缺席系数；缺失时退回中等。"""
    if not raw:
        return AbsenceDispositionFactors()
    attachment = _weight(raw.get("attachment_tendency"))
    dependency = _weight(raw.get("emotional_dependency_tendency"))
    separation = _weight(raw.get("separation_sensitivity"))
    reassurance = _weight(raw.get("reassurance_need"))
    return AbsenceDispositionFactors(
        longing_factor=round(0.45 * attachment + 0.55 * separation, 4),
        anxiety_factor=round(0.5 * dependency + 0.5 * reassurance, 4),
        separation_factor=separation,
        dependency_factor=dependency,
        reassurance_factor=reassurance,
    )


def plan_maintenance(
    emotion: EmotionState,
    interaction: InteractionState,
    now: datetime,
    *,
    relationship: RelationshipState | None = None,
    absence_factors: AbsenceDispositionFactors | None = None,
    half_life_multipliers: Mapping[str, float] | None = None,
) -> MaintenancePlan:
    moment = _aware(now)
    factors = absence_factors or AbsenceDispositionFactors()
    decayed, decay_reason = _decay_emotion(emotion, moment, half_life_multipliers=half_life_multipliers)
    seed = decayed or _as_input(emotion)
    absence = _absence_emotion(seed, interaction, moment, factors)
    final_emotion = absence or decayed
    emotion_reason = None
    if absence is not None and decayed is not None:
        emotion_reason = f"{decay_reason or EMOTION_REASON}；{ABSENCE_REASON}"
    elif absence is not None:
        emotion_reason = ABSENCE_REASON
    elif decayed is not None:
        emotion_reason = decay_reason or EMOTION_REASON

    relationship_update = None
    relationship_reason = None
    if absence is not None and relationship is not None:
        relationship_update = _absence_relationship(relationship, factors)
        if relationship_update is not None:
            relationship_reason = ABSENCE_RELATIONSHIP_REASON

    return MaintenancePlan(
        emotion=final_emotion,
        interaction=_expire_quiet(interaction, moment),
        relationship=relationship_update,
        emotion_reason=emotion_reason,
        relationship_reason=relationship_reason,
    )


def _decay_emotion(
    emotion: EmotionState,
    now: datetime,
    *,
    half_life_multipliers: Mapping[str, float] | None = None,
) -> tuple[EmotionInput | None, str | None]:
    elapsed = now - _aware(emotion.updated_at)
    if elapsed < _MIN_ELAPSED:
        return None, None
    seeded = _seed_levels_from_legacy(emotion)
    after_levels = decay_levels(seeded.levels, elapsed, half_life_multipliers=half_life_multipliers)
    before_levels = normalize_levels(seeded.levels)
    possessiveness = _legacy_lower(emotion.possessiveness, elapsed)
    emotional_tension = _legacy_lower(emotion.emotional_tension, elapsed)
    if after_levels == before_levels and possessiveness == emotion.possessiveness and emotional_tension == emotion.emotional_tension:
        return None, None
    resting = all(value <= 0.05 for value in after_levels.values())
    if resting and possessiveness == 0 and emotional_tension == 0:
        if (
            emotion.primary in {"calm", "平静"}
            and emotion.intensity == 0
            and emotion.arousal == 0
            and emotion.valence == 0
            and emotion.jealousy == 0
            and emotion.possessiveness == 0
            and emotion.emotional_tension == 0
            and not emotion.secondary
            and not emotion.triggers
            and max(normalize_levels(emotion.levels).values()) <= 0.05
        ):
            return None, None
        return (
            EmotionInput(
                primary="平静",
                secondary=[],
                intensity=0,
                valence=0,
                arousal=0,
                jealousy=0,
                possessiveness=0,
                emotional_tension=0,
                triggers=[],
                cause_summary=SETTLED_CAUSE,
                levels={key: 0.0 for key in EMOTION_KEYS},
            ),
            EMOTION_REASON,
        )
    legacy = sync_legacy_from_levels(after_levels)
    primary = str(legacy["primary"])
    # 衰减中途保留原有可读中文标签，避免无意义抖动。
    mapped = _legacy_primary_key(emotion.primary)
    if emotion.primary not in {"calm", "平静"} and primary != "平静" and mapped is not None:
        if emotion_display_name(mapped) == primary or emotion.primary == primary:
            primary = emotion.primary
    return (
        EmotionInput(
            primary=primary,
            secondary=list(emotion.secondary) if primary == emotion.primary else [str(item) for item in legacy["secondary"]],  # type: ignore[index]
            intensity=float(legacy["intensity"]),
            valence=float(legacy["valence"]),
            arousal=float(legacy["arousal"]),
            jealousy=float(legacy["jealousy"]),
            possessiveness=possessiveness,
            emotional_tension=emotional_tension,
            triggers=list(emotion.triggers),
            cause_summary=emotion.cause_summary,
            levels=after_levels,
        ),
        EMOTION_REASON,
    )


def _absence_emotion(
    current: EmotionInput,
    interaction: InteractionState,
    now: datetime,
    factors: AbsenceDispositionFactors,
) -> EmotionInput | None:
    last = interaction.last_user_response_at
    if last is None:
        return None
    if now - _aware(last) < _ABSENCE_GAP:
        return None
    # 想念已经偏高时不再重复叠加，避免维护任务刷屏。
    if normalize_levels(current.levels).get("longing", 0) >= _ABSENCE_LONGING_CAP:
        return None
    # 先按中等基线算事件，再分别用依恋/分离与依赖/确认需求缩放想念与不安。
    base = compute_event_deltas(
        EmotionEventKind.USER_ABSENCE,
        intensity=0.55,
        confidence=0.85,
        persona_factor=1.0,
    )
    scaled = {
        "longing": clamp_level(base.get("longing", 0.0) * max(0.2, factors.longing_factor)),
        "anxiety": clamp_level(base.get("anxiety", 0.0) * max(0.2, factors.anxiety_factor)),
    }
    after = apply_deltas(current.levels, scaled)
    if after == normalize_levels(current.levels):
        return None
    legacy = sync_legacy_from_levels(after)
    return EmotionInput(
        primary=str(legacy["primary"]),
        secondary=[str(item) for item in legacy["secondary"]],  # type: ignore[index]
        intensity=float(legacy["intensity"]),
        valence=float(legacy["valence"]),
        arousal=float(legacy["arousal"]),
        jealousy=float(legacy["jealousy"]),
        possessiveness=current.possessiveness,
        emotional_tension=_clamp_unit(
            current.emotional_tension + 0.03 * max(0.2, factors.separation_factor)
        ),
        triggers=list(current.triggers),
        cause_summary=ABSENCE_REASON,
        levels=after,
    )


def _absence_relationship(
    current: RelationshipState,
    factors: AbsenceDispositionFactors,
) -> RelationshipState | None:
    desire = _clamp_unit(current.closeness_desire + 0.04 * max(0.2, factors.separation_factor))
    separation = _clamp_unit(
        current.separation_sensitivity + 0.025 * max(0.2, factors.separation_factor)
    )
    reliance = _clamp_unit(current.emotional_reliance + 0.02 * max(0.2, factors.dependency_factor))
    reassurance = _clamp_unit(
        current.reassurance_satisfaction - 0.025 * max(0.2, factors.reassurance_factor)
    )
    updated = current.model_copy(
        update={
            "closeness_desire": desire,
            "separation_sensitivity": separation,
            "emotional_reliance": reliance,
            "reassurance_satisfaction": reassurance,
        }
    )
    if updated == current:
        return None
    return updated


def _as_input(emotion: EmotionState) -> EmotionInput:
    return EmotionInput(
        primary=emotion.primary,
        secondary=list(emotion.secondary),
        intensity=emotion.intensity,
        valence=emotion.valence,
        arousal=emotion.arousal,
        jealousy=emotion.jealousy,
        possessiveness=emotion.possessiveness,
        emotional_tension=emotion.emotional_tension,
        triggers=list(emotion.triggers),
        cause_summary=emotion.cause_summary,
        levels=normalize_levels(emotion.levels),
    )


def _seed_levels_from_legacy(emotion: EmotionState) -> EmotionState:
    levels = normalize_levels(emotion.levels)
    if max(levels.values()) > 0.05:
        return emotion.model_copy(update={"levels": levels})
    if emotion.intensity <= 0 and emotion.jealousy <= 0:
        return emotion.model_copy(update={"levels": levels})
    key = _legacy_primary_key(emotion.primary)
    if emotion.intensity > 0 and key is not None:
        levels[key] = max(levels[key], round(emotion.intensity * 100.0, 2))
    if emotion.jealousy > 0:
        levels["jealousy"] = max(levels["jealousy"], round(emotion.jealousy * 100.0, 2))
    return emotion.model_copy(update={"levels": levels})


def _legacy_primary_key(primary: str) -> str | None:
    mapping = {
        "happy": "joy",
        "joy": "joy",
        "开心": "joy",
        "engaged": "excitement",
        "投入": "excitement",
        "curious": "excitement",
        "好奇": "excitement",
        "moved": "affection",
        "触动": "affection",
        "亲密": "affection",
        "attentive": "comfort",
        "专注": "comfort",
        "安心": "comfort",
        "calm": None,
        "平静": None,
    }
    if primary in EMOTION_KEYS:
        return primary
    return mapping.get(primary, "joy")


def _legacy_lower(value: float, elapsed: timedelta) -> float:
    ratio = elapsed.total_seconds() / EMOTION_DECAY_WINDOW.total_seconds()
    if ratio > 1:
        ratio = 1
    reduced = value - ratio
    return 0.0 if reduced < 0 else round(reduced, 3)


def _expire_quiet(interaction: InteractionState, now: datetime) -> InteractionState | None:
    if interaction.quiet_until is None or _aware(interaction.quiet_until) > now:
        return None
    mode = InteractionMode.AVAILABLE if interaction.mode == InteractionMode.QUIET else interaction.mode
    updated = interaction.model_copy(update={"mode": mode, "quiet_until": None})
    if updated == interaction:
        return None
    return updated


def _weight(value: object) -> float:
    if isinstance(value, str):
        return _TENDENCY_WEIGHT.get(value.strip().lower(), 1.0)
    return 1.0


def _clamp_unit(value: float) -> float:
    number = Decimal(str(value)).quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return float(number)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
