"""定时主动检查先看约束、间隔和依恋准备度。通过之后才交给交流决策决定发不发。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.modules.conversation.domain.enums import SenderType
from app.modules.state.domain.enums import InteractionEnergy

MIN_PROACTIVE_GAP = timedelta(hours=2)
LOW_ENERGY_PROACTIVE_GAP = timedelta(hours=4)
HIGH_DESIRE_USER_SILENCE = timedelta(hours=3)
MEDIUM_DESIRE_USER_SILENCE = timedelta(hours=6)
DEFAULT_USER_SILENCE = timedelta(hours=8)
EARLY_STAGE_USER_SILENCE = timedelta(hours=12)
USER_TURN_GRACE = timedelta(minutes=15)
MAX_UNANSWERED_COMPANION_MESSAGES = 2


@dataclass(frozen=True)
class ProactiveMessage:
    sender_type: str
    created_at: datetime


@dataclass(frozen=True)
class ProactiveAttachmentCue:
    """主动联系前的依恋准备度。数值只供内部判断。"""

    closeness_desire: float = 0.0
    attachment_strength: float = 0.0
    separation_sensitivity: float = 0.0


def frequency_block(
    messages: list[ProactiveMessage],
    now: datetime,
    energy: InteractionEnergy | str | None = None,
) -> str | None:
    """连续开口有上限。刚刚收到用户消息时，把回应留给当前回合。"""
    level = _energy(energy)
    if level == InteractionEnergy.QUIET:
        return "energy_quiet"
    if not messages:
        return None
    moment = _aware(now)
    last = messages[-1]
    age = moment - _aware(last.created_at)
    if last.sender_type == SenderType.USER.value and age < USER_TURN_GRACE:
        return "awaiting_reply"
    trailing = 0
    for item in reversed(messages):
        if item.sender_type == SenderType.USER.value:
            break
        if item.sender_type == SenderType.COMPANION.value:
            trailing += 1
    if trailing >= MAX_UNANSWERED_COMPANION_MESSAGES:
        return "unanswered_limit"
    gap = LOW_ENERGY_PROACTIVE_GAP if level == InteractionEnergy.LOW else MIN_PROACTIVE_GAP
    if last.sender_type == SenderType.COMPANION.value and age < gap:
        return "too_recent"
    return None


def attachment_silence_block(
    messages: list[ProactiveMessage],
    now: datetime,
    cue: ProactiveAttachmentCue | None = None,
) -> str | None:
    """按依恋准备度要求最短用户沉默时间。高靠近意愿可更早进入决策，初识更克制。"""
    last_user = _last_user(messages)
    if last_user is None:
        return None
    silence = _aware(now) - _aware(last_user.created_at)
    required = required_user_silence(cue)
    if silence < required:
        return "user_silence_too_short"
    return None


def required_user_silence(cue: ProactiveAttachmentCue | None = None) -> timedelta:
    """靠近意愿/依恋强度决定主动联系前需要等多久。不等于一定会发消息。"""
    state = cue or ProactiveAttachmentCue()
    desire = _unit(state.closeness_desire)
    strength = _unit(state.attachment_strength)
    separation = _unit(state.separation_sensitivity)
    weighted_desire = desire + separation * 0.15
    if strength < 0.15 and weighted_desire < 0.25:
        return EARLY_STAGE_USER_SILENCE
    if weighted_desire >= 0.6 or (weighted_desire >= 0.45 and strength >= 0.5):
        return HIGH_DESIRE_USER_SILENCE
    if weighted_desire >= 0.3 or strength >= 0.35:
        return MEDIUM_DESIRE_USER_SILENCE
    return DEFAULT_USER_SILENCE


def _last_user(messages: list[ProactiveMessage]) -> ProactiveMessage | None:
    for item in reversed(messages):
        if item.sender_type == SenderType.USER.value:
            return item
    return None


def _energy(value: InteractionEnergy | str | None) -> InteractionEnergy:
    if value is None:
        return InteractionEnergy.NORMAL
    if isinstance(value, InteractionEnergy):
        return value
    try:
        return InteractionEnergy(value)
    except ValueError:
        return InteractionEnergy.NORMAL


def _unit(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return float(value)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
