"""临时情绪会过去，到期的安静时段会结束。关系和动机不在这里改。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.modules.state.domain.enums import InteractionMode
from app.modules.state.domain.snapshots import EmotionInput, EmotionState, InteractionState

EMOTION_DECAY_WINDOW = timedelta(hours=6)
_MIN_ELAPSED = timedelta(minutes=1)
_THOUSANDTH = Decimal("0.001")
SETTLED_CAUSE = "临时情绪已经过去"
EMOTION_REASON = "临时情绪随时间衰减"
QUIET_REASON = "安静时段已经结束"


@dataclass(frozen=True)
class MaintenancePlan:
    emotion: EmotionInput | None = None
    interaction: InteractionState | None = None

    @property
    def reason(self) -> str | None:
        parts: list[str] = []
        if self.emotion is not None:
            parts.append(EMOTION_REASON)
        if self.interaction is not None:
            parts.append(QUIET_REASON)
        if not parts:
            return None
        return "；".join(parts)


def plan_maintenance(emotion: EmotionState, interaction: InteractionState, now: datetime) -> MaintenancePlan:
    return MaintenancePlan(
        emotion=_decay_emotion(emotion, _aware(now)),
        interaction=_expire_quiet(interaction, _aware(now)),
    )


def _decay_emotion(emotion: EmotionState, now: datetime) -> EmotionInput | None:
    elapsed = now - _aware(emotion.updated_at)
    if elapsed < _MIN_ELAPSED:
        return None
    ratio = Decimal(str(elapsed.total_seconds())) / Decimal(str(EMOTION_DECAY_WINDOW.total_seconds()))
    if ratio > 1:
        ratio = Decimal(1)
    intensity = _lower(emotion.intensity, ratio)
    arousal = _lower(emotion.arousal, ratio)
    valence = _lower(emotion.valence, ratio)
    jealousy = _lower(emotion.jealousy, ratio)
    possessiveness = _lower(emotion.possessiveness, ratio)
    emotional_tension = _lower(emotion.emotional_tension, ratio)
    primary = emotion.primary
    secondary = list(emotion.secondary)
    triggers = list(emotion.triggers)
    cause = emotion.cause_summary
    resting = (
        intensity == 0
        and arousal == 0
        and valence == 0
        and jealousy == 0
        and possessiveness == 0
        and emotional_tension == 0
        and primary == "calm"
        and not secondary
        and not triggers
    )
    if (
        resting
        and emotion.intensity == 0
        and emotion.arousal == 0
        and emotion.valence == 0
        and emotion.jealousy == 0
        and emotion.possessiveness == 0
        and emotion.emotional_tension == 0
        and not emotion.secondary
        and not emotion.triggers
    ):
        return None
    if intensity == 0 and arousal == 0 and jealousy == 0 and possessiveness == 0 and emotional_tension == 0:
        primary = "calm"
        secondary = []
        triggers = []
        valence = 0
        cause = SETTLED_CAUSE
    if (
        intensity == emotion.intensity
        and arousal == emotion.arousal
        and valence == emotion.valence
        and jealousy == emotion.jealousy
        and possessiveness == emotion.possessiveness
        and emotional_tension == emotion.emotional_tension
        and primary == emotion.primary
        and secondary == list(emotion.secondary)
        and triggers == list(emotion.triggers)
        and cause == emotion.cause_summary
    ):
        return None
    return EmotionInput(
        primary=primary,
        secondary=secondary,
        intensity=intensity,
        valence=valence,
        arousal=arousal,
        jealousy=jealousy,
        possessiveness=possessiveness,
        emotional_tension=emotional_tension,
        triggers=triggers,
        cause_summary=cause,
    )


def _expire_quiet(interaction: InteractionState, now: datetime) -> InteractionState | None:
    if interaction.quiet_until is None or _aware(interaction.quiet_until) > now:
        return None
    mode = InteractionMode.AVAILABLE if interaction.mode == InteractionMode.QUIET else interaction.mode
    updated = interaction.model_copy(update={"mode": mode, "quiet_until": None})
    if updated == interaction:
        return None
    return updated


def _lower(value: float, ratio: Decimal) -> float:
    reduced = Decimal(str(value)) - ratio
    if reduced < 0:
        reduced = Decimal(0)
    return float(reduced.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
