import uuid

from app.modules.memory.domain.enums import MemoryType
from app.modules.memory.domain.extraction import ExtractionCategory


def formal_memory_type(memory_type: MemoryType, category: ExtractionCategory) -> MemoryType | None:
    """未完成事项进入会话工作记忆。其余内容只写成语义或情景记忆。"""
    if category == ExtractionCategory.OPEN_LOOP:
        return None
    if category == ExtractionCategory.EMOTION or (
        memory_type == MemoryType.WORKING and category == ExtractionCategory.EVENT
    ):
        return MemoryType.EPISODIC
    if memory_type == MemoryType.WORKING:
        return MemoryType.SEMANTIC
    return memory_type


def parse_topic_id(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def next_topic_label(
    current_topic: str | None,
    transition: str | None,
    topic_id: str | None,
) -> str | None:
    if transition == "close":
        return None
    if transition == "new_topic":
        label = (topic_id or "").strip()
        return label or current_topic
    return current_topic
