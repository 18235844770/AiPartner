import json
import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.memory.domain.enums import MemoryType
from app.modules.model_adapter.domain.messages import ChatMessage


class ExtractionCategory(StrEnum):
    """记忆方案 3.2 列出的提取类别。"""

    FACT = "fact"
    PREFERENCE = "preference"
    HABIT = "habit"
    PLAN = "plan"
    EVENT = "event"
    RELATIONSHIP = "relationship"
    OPINION = "opinion"
    EMOTION = "emotion"
    OPEN_LOOP = "open_loop"
    THEME = "theme"


class MemoryWriteAction(StrEnum):
    CREATE = "create"
    SUPPLEMENT = "supplement"
    CORRECT = "correct"
    IGNORE = "ignore"


class ExtractedMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MemoryWriteAction = MemoryWriteAction.CREATE
    target_memory_id: uuid.UUID | None = None
    memory_type: MemoryType
    category: ExtractionCategory
    subject: str | None = Field(default=None, max_length=128)
    explicit: bool = False
    content: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=200)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped

    @field_validator("subject", "summary")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def action_has_target(self) -> "ExtractedMemory":
        if self.action in {MemoryWriteAction.SUPPLEMENT, MemoryWriteAction.CORRECT}:
            if self.target_memory_id is None:
                raise ValueError("补充或修正必须指定已有记忆")
        else:
            self.target_memory_id = None
        return self


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[ExtractedMemory] = Field(default_factory=list, max_length=8)


_SYSTEM = (
    "你只输出一个 JSON 对象，包含 memories 数组。"
    "只根据给出的用户消息和已有记忆做决定，不要编造没有出现的经历。"
    "action 只能是 create、supplement、correct、ignore。"
    "已有记忆仍然正确、只是增加细节时用 supplement。"
    "用户明确否定或更正已有记忆时用 correct。"
    "没有新信息或与已有记忆重复时用 ignore。"
    "只有找不到对应的已有记忆时才用 create。create 只是候选，不是正式记忆。"
    "supplement 和 correct 必须填写 target_memory_id，且只能使用给出的已有记忆编号。"
    "无法判断新旧哪一个正确时用 ignore，不要覆盖。"
    "explicit 仅当用户直接说出该事实时为 true，推测必须为 false。"
    "不要把一次情绪写成稳定的性格判断。没有值得保留的信息时返回空数组。"
    "category 只能是 fact、preference、habit、plan、event、relationship、opinion、emotion、open_loop、theme。"
    "memory_type 只能是 working、semantic、episodic。"
)

_EXISTING_LIMIT = 20


def extraction_messages(content: str, existing: list[dict[str, object]]) -> list[ChatMessage]:
    body = {
        "message": content,
        "existing_memories": existing[:_EXISTING_LIMIT],
    }
    return [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
    ]
