"""定时主动检查先看约束和间隔。通过之后才交给交流决策决定发不发。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.modules.conversation.domain.enums import SenderType

MIN_PROACTIVE_GAP = timedelta(hours=2)
USER_TURN_GRACE = timedelta(minutes=15)
MAX_UNANSWERED_COMPANION_MESSAGES = 2


@dataclass(frozen=True)
class ProactiveMessage:
    sender_type: str
    created_at: datetime


def frequency_block(messages: list[ProactiveMessage], now: datetime) -> str | None:
    """连续开口有上限。刚刚收到用户消息时，把回应留给当前回合。"""
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
    if last.sender_type == SenderType.COMPANION.value and age < MIN_PROACTIVE_GAP:
        return "too_recent"
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
