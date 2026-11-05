import re
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app.modules.memory.domain.enums import MemoryOrigin, MemoryStatus

RETRIEVAL_LIMIT = 8

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


def source_is_reliable(*, origin: str, is_inference: bool, has_message_evidence: bool) -> bool:
    if has_message_evidence:
        return True
    return origin == MemoryOrigin.USER_EXPLICIT.value and not is_inference


def retrieval_allowed(
    *,
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
) -> bool:
    """资格先于排序。过期、拒绝和不可靠候选不能靠高分进入上下文。"""
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
    return reliable and related


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
