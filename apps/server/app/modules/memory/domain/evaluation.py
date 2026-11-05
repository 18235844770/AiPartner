import json
import uuid
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.model_adapter.domain.messages import ChatMessage

_THOUSANDTH = Decimal("0.001")


def _unit(value: Decimal) -> Decimal:
    quantized = value.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)
    if quantized < 0 or quantized > 1:
        raise ValueError("评分必须在 0 到 1 之间")
    return quantized


class MemoryScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: uuid.UUID
    importance: Decimal = Field(ge=0, le=1)
    stability: Decimal = Field(ge=0, le=1)
    repetition: Decimal = Field(ge=0, le=1)
    relatedness: Decimal = Field(ge=0, le=1)
    freshness: Decimal = Field(ge=0, le=1)
    confidence: Decimal = Field(ge=0, le=1)
    relevance: Decimal = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator(
        "importance",
        "stability",
        "repetition",
        "relatedness",
        "freshness",
        "confidence",
        "relevance",
    )
    @classmethod
    def quantize_unit(cls, value: Decimal) -> Decimal:
        return _unit(value)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class EvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluations: list[MemoryScore] = Field(default_factory=list, max_length=8)


def importance_points(importance: Decimal) -> int:
    return int((importance * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quality_score(
    *,
    importance: Decimal,
    stability: Decimal,
    repetition: Decimal,
    relatedness: Decimal,
    freshness: Decimal,
) -> Decimal:
    """设计文档中的辅助评分，不决定删除或升为正式记忆。"""
    total = (
        Decimal("0.30") * importance
        + Decimal("0.25") * stability
        + Decimal("0.15") * repetition
        + Decimal("0.20") * relatedness
        + Decimal("0.10") * freshness
    )
    return total.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)


_SYSTEM = (
    "你只输出一个 JSON 对象，包含 evaluations 数组。"
    "只为给出的记忆评分，不要编造新记忆，不要修改记忆正文。"
    "importance、stability、repetition、relatedness、freshness、confidence、relevance 都是 0 到 1。"
    "importance 是重要性，stability 是稳定性，repetition 是重复性，relatedness 是关联性，freshness 是时效性。"
    "confidence 是这条记忆目前的可信度，relevance 是当前相关性。"
    "单次出现不能单独降低重要性。用户一次情绪不能写成稳定性格。"
    "评分只供以后判断是否保留，不能把候选记忆升为正式记忆，也不能建议删除。"
    "没有给出的记忆不要评分。"
)


def evaluation_messages(content: str, memories: list[dict[str, object]]) -> list[ChatMessage]:
    body = {"message": content, "memories": memories[:8]}
    return [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=json.dumps(body, ensure_ascii=False)),
    ]
