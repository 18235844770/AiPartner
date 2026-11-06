"""在已有记忆之间建立关联。模型只建议关系，不新增事实。"""

import json
import uuid
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.memory.domain.enums import MemoryRelationType
from app.modules.model_adapter.domain.messages import ChatMessage

_THOUSANDTH = Decimal("0.001")


def _unit(value: Decimal) -> Decimal:
    quantized = value.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)
    if quantized < 0 or quantized > 1:
        raise ValueError("关联强度必须在 0 到 1 之间")
    return quantized


class RelationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_memory_id: uuid.UUID
    target_memory_id: uuid.UUID
    relation_type: MemoryRelationType
    strength: Decimal = Field(ge=0, le=1)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("strength")
    @classmethod
    def quantize_strength(cls, value: Decimal) -> Decimal:
        return _unit(value)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class RelationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relations: list[RelationProposal] = Field(default_factory=list, max_length=8)


_SYSTEM = (
    "你只输出一个 JSON 对象，包含 relations 数组。"
    "只连接给出的记忆，不要编造新记忆，也不要把推断写成用户明确说过的话。"
    "关系只表示人物、事件或目标之间已经能从这些记忆里看出的联系。"
    "至少一端必须是 from_message 为 true 的记忆。无法确定时返回空数组。"
    "relation_type 只能是 related_to、supports、contradicts、supersedes、caused_by、part_of。"
    "strength 是 0 到 1 的关联强度。description 只解释这条联系，不能补充新的用户事实。"
    "不要把一条记忆连到它自己。"
)


def relation_messages(content: str, memories: list[dict[str, object]]) -> list[ChatMessage]:
    body = {"message": content, "memories": memories[:20]}
    return [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
    ]
