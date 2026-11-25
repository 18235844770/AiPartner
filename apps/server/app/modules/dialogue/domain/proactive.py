"""定时主动检查先看约束、间隔和依恋准备度。通过之后才交给交流决策决定发不发。

用户不在对话里也可以开口。间隔按分钟计，同一轮拆开的几条气泡算一次联系。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.modules.conversation.domain.enums import SenderType
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion
from app.modules.state.domain.enums import InteractionEnergy

MIN_PROACTIVE_GAP = timedelta(minutes=20)
LOW_ENERGY_PROACTIVE_GAP = timedelta(minutes=40)
HIGH_DESIRE_USER_SILENCE = timedelta(minutes=15)
MEDIUM_DESIRE_USER_SILENCE = timedelta(minutes=30)
DEFAULT_USER_SILENCE = timedelta(minutes=45)
EARLY_STAGE_USER_SILENCE = timedelta(minutes=60)
USER_TURN_GRACE = timedelta(minutes=5)
MAX_UNANSWERED_COMPANION_MESSAGES = 4
OUTREACH_BURST = timedelta(minutes=2)
SCHEDULE_SLOT = timedelta(minutes=5)


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


def schedule_bucket(moment: datetime) -> str:
    """同一 5 分钟槽只排一次检查。人离开界面之后，下一次槽仍会再排。"""
    aware = _aware(moment)
    slot = (aware.minute // int(SCHEDULE_SLOT.total_seconds() // 60)) * int(SCHEDULE_SLOT.total_seconds() // 60)
    return f"{aware.strftime('%Y%m%d%H')}{slot:02d}"


def speak_when_user_is_absent(
    suggestion: ModelDecisionSuggestion,
) -> tuple[ModelDecisionSuggestion, dict[str, object]]:
    """检查已经通过时间门时，对方不在场不是继续安静的理由。模型失败的降级不走这里。"""
    if suggestion.should_send and suggestion.primary_action != DialogueAction.QUIET:
        return suggestion, {"proactive_gate": "accepted"}
    note = "对方现在不在，这一轮仍然开口"
    reason = suggestion.reasoning_summary
    if note not in reason:
        reason = f"{reason}；{note}"
    motivation = suggestion.self_motivation
    if motivation.kind == SelfMotivationKind.NONE:
        motivation = motivation.model_copy(
            update={
                "kind": SelfMotivationKind.SEEK_CONNECTION,
                "desire_to_express": "主动说一件具体的事",
            }
        )
    updated = suggestion.model_copy(
        update={
            "should_send": True,
            "primary_action": DialogueAction.SHARE,
            "secondary_actions": [],
            "self_motivation": motivation,
            "reasoning_summary": reason,
        }
    )
    return updated, {"proactive_gate": "speak_while_absent", "should_send": True}


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
    if _trailing_outreach_bursts(messages) >= MAX_UNANSWERED_COMPANION_MESSAGES:
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


def _trailing_outreach_bursts(messages: list[ProactiveMessage]) -> int:
    """连续未回复按一次次开口计。同一轮拆开的气泡相隔很近，只算一次。"""
    bursts = 0
    newer: datetime | None = None
    for item in reversed(messages):
        if item.sender_type == SenderType.USER.value:
            break
        if item.sender_type != SenderType.COMPANION.value:
            continue
        created = _aware(item.created_at)
        if newer is None or newer - created > OUTREACH_BURST:
            bursts += 1
        newer = created
    return bursts


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
