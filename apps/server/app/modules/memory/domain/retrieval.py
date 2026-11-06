import math
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.modules.memory.domain.enums import MemoryOrigin, MemoryStatus, MemoryType

RETRIEVAL_LIMIT = 8
VECTOR_MATCH_FLOOR = 0.55

_TERM = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")
_OPEN = {MemoryStatus.CANDIDATE.value, MemoryStatus.PENDING.value, MemoryStatus.ACTIVE.value}
_STATUS_WEIGHT = {
    MemoryStatus.ACTIVE.value: Decimal("1.000"),
    MemoryStatus.PENDING.value: Decimal("0.750"),
    MemoryStatus.CANDIDATE.value: Decimal("0.500"),
    MemoryStatus.ARCHIVED.value: Decimal("0.250"),
}


def topic_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    for match in _TERM.finditer(text):
        token = match.group(0).lower()
        if re.fullmatch(r"[a-z0-9]+", token):
            if len(token) >= 2:
                fragments.add(token)
            continue
        for index in range(len(token) - 1):
            fragments.add(token[index : index + 2])
    return fragments


def topic_related(query: str, *parts: str | None) -> bool:
    needles = topic_fragments(query)
    if not needles:
        return False
    haystack = " ".join(part or "" for part in parts).lower()
    return any(needle in haystack for needle in needles)


def query_time_window(query: str, now: datetime) -> tuple[datetime, datetime] | None:
    """问句里出现明确时间时返回区间，终点不含在内。没有时间用语时不启用时间通道。"""
    if "上周" in query:
        start = _week_start(now) - timedelta(days=7)
        return start, start + timedelta(days=7)
    if "下周" in query:
        start = _week_start(now) + timedelta(days=7)
        return start, start + timedelta(days=7)
    if "本周" in query:
        start = _week_start(now)
        return start, start + timedelta(days=7)
    if "昨天" in query:
        start = _day_start(now) - timedelta(days=1)
        return start, start + timedelta(days=1)
    if "明天" in query:
        start = _day_start(now) + timedelta(days=1)
        return start, start + timedelta(days=1)
    if "今天" in query:
        start = _day_start(now)
        return start, start + timedelta(days=1)
    if "最近" in query or "近期" in query:
        start = _day_start(now) - timedelta(days=6)
        return start, start + timedelta(days=1)
    return None


def episodic_in_window(memory_type: str, moment: datetime | None, window: tuple[datetime, datetime] | None) -> bool:
    if memory_type != MemoryType.EPISODIC.value or moment is None or window is None:
        return False
    start, end = window
    return start <= moment < end


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for first, second in zip(left, right, strict=True):
        dot += first * second
        left_norm += first * first
        right_norm += second * second
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    value = dot / math.sqrt(left_norm * right_norm)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def vector_matches(similarity: float) -> bool:
    return similarity >= VECTOR_MATCH_FLOOR


def source_is_reliable(*, origin: str, is_inference: bool, has_message_evidence: bool) -> bool:
    if has_message_evidence:
        return True
    return origin == MemoryOrigin.USER_EXPLICIT.value and not is_inference


def retrieval_allowed(
    *,
    memory_type: str = "semantic",
    status: str,
    origin: str,
    is_inference: bool,
    content: str,
    valid_from: datetime | None,
    valid_until: datetime | None,
    has_message_evidence: bool,
    query: str,
    subject: str | None,
    summary: str | None,
    category: str,
    now: datetime,
    include_archived: bool,
    vector_match: bool = False,
    time_match: bool = False,
    relation_match: bool = False,
) -> bool:
    """资格先于排序。过期、拒绝和不可靠候选不能靠高分进入上下文。"""
    if memory_type == MemoryType.WORKING.value:
        return False
    if status == MemoryStatus.REJECTED.value:
        return False
    if status == MemoryStatus.ARCHIVED.value and not include_archived:
        return False
    if status not in _OPEN and status != MemoryStatus.ARCHIVED.value:
        return False
    if not content.strip():
        return False
    if valid_from is not None and valid_from > now:
        return False
    if valid_until is not None and valid_until < now:
        return False
    if status != MemoryStatus.CANDIDATE.value:
        return True
    reliable = source_is_reliable(
        origin=origin,
        is_inference=is_inference,
        has_message_evidence=has_message_evidence,
    )
    related = topic_related(query, content, summary, subject, category)
    return reliable and (related or vector_match or time_match or relation_match)


def retrieval_score(
    *,
    related: bool,
    confidence: Decimal,
    reliable: bool,
    status: str,
    importance: int,
) -> Decimal:
    """只用于已通过资格的记忆排序，不决定能否使用，也不决定晋升。"""
    total = (
        Decimal("0.35") * (Decimal("1") if related else Decimal("0"))
        + Decimal("0.25") * confidence
        + Decimal("0.15") * (Decimal("1") if reliable else Decimal("0"))
        + Decimal("0.15") * _STATUS_WEIGHT.get(status, Decimal("0"))
        + Decimal("0.10") * (Decimal(importance) / Decimal("100"))
    )
    return total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def source_summary(*, origin: str, is_inference: bool, source_count: int) -> str:
    if is_inference:
        return f"推断，来源 {source_count} 条"
    if origin == MemoryOrigin.USER_EXPLICIT.value:
        return "用户明确表达"
    if source_count:
        return f"来源 {source_count} 条"
    return "来源未记录"


def retrieval_context(
    *,
    memory_id: uuid.UUID,
    memory_type: str,
    memory_status: str,
    content: str,
    confidence: Decimal,
    is_inference: bool,
    origin: str,
    source_count: int,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> dict[str, object]:
    return {
        "memory_id": str(memory_id),
        "memory_type": memory_type,
        "memory_status": memory_status,
        "content": content,
        "confidence": f"{confidence.quantize(Decimal('0.001'))}",
        "is_inference": is_inference,
        "source_summary": source_summary(origin=origin, is_inference=is_inference, source_count=source_count),
        "valid_from": valid_from.isoformat() if valid_from is not None else None,
        "valid_until": valid_until.isoformat() if valid_until is not None else None,
    }


def _day_start(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start(moment: datetime) -> datetime:
    start = _day_start(moment)
    return start - timedelta(days=start.weekday())
