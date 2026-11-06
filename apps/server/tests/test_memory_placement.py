import uuid

import pytest
from pydantic import ValidationError

from app.modules.memory.api.schemas import CreateMemoryRequest
from app.modules.memory.domain.enums import MemoryOrigin, MemoryType
from app.modules.memory.domain.extraction import ExtractionCategory
from app.modules.memory.domain.placement import formal_memory_type, next_topic_label, parse_topic_id


def test_open_loops_stay_out_of_formal_memory() -> None:
    assert formal_memory_type(MemoryType.WORKING, ExtractionCategory.OPEN_LOOP) is None
    assert formal_memory_type(MemoryType.SEMANTIC, ExtractionCategory.OPEN_LOOP) is None
    assert formal_memory_type(MemoryType.WORKING, ExtractionCategory.FACT) == MemoryType.SEMANTIC
    assert formal_memory_type(MemoryType.WORKING, ExtractionCategory.EVENT) == MemoryType.EPISODIC
    assert formal_memory_type(MemoryType.SEMANTIC, ExtractionCategory.EMOTION) == MemoryType.EPISODIC
    assert formal_memory_type(MemoryType.SEMANTIC, ExtractionCategory.PREFERENCE) == MemoryType.SEMANTIC


def test_topic_transition_updates_the_live_label() -> None:
    assert next_topic_label("架构", "continue", None) == "架构"
    assert next_topic_label("架构", "close", "别的") is None
    assert next_topic_label("架构", "new_topic", "记忆检索") == "记忆检索"
    assert next_topic_label("架构", "new_topic", "  ") == "架构"
    assert parse_topic_id("不是编号") is None
    parsed = parse_topic_id(str(uuid.uuid4()))
    assert parsed is not None


def test_create_memory_rejects_working_type() -> None:
    with pytest.raises(ValidationError):
        CreateMemoryRequest(
            memory_type=MemoryType.WORKING,
            memory_category="context",
            memory_origin=MemoryOrigin.SYSTEM_GENERATED,
            content="当前正在讨论记忆模块",
            change_reason="会话上下文",
        )
