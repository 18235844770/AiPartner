import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.infrastructure.domain.enums import ModelConfigKey
from app.modules.memory.domain.enums import MemoryStatus
from app.modules.memory.domain.evaluation import (
    EvaluationOutput,
    MemoryScore,
    evaluation_messages,
    importance_points,
    quality_score,
)
from app.modules.memory.repositories.models import Memory, MemoryVersion
from app.modules.memory.services.memory_service import MemoryService
from app.modules.model_adapter.domain.messages import ChatMessage
from app.modules.model_adapter.services.model_adapter import ModelCallScope

logger = logging.getLogger(__name__)

_SKIPPABLE = {MemoryStatus.ARCHIVED.value, MemoryStatus.REJECTED.value}


class EvaluationModel(Protocol):
    async def complete_structured(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        result_type: type[EvaluationOutput],
        scope: ModelCallScope,
    ) -> EvaluationOutput: ...


class MemoryEvaluationService:
    def __init__(
        self,
        memories: MemoryService | None = None,
        conversations: ConversationService | None = None,
        adapter: EvaluationModel | None = None,
    ) -> None:
        self._memories = memories or MemoryService()
        self._conversations = conversations or ConversationService()
        self._adapter = adapter if adapter is not None else _default_adapter()

    async def evaluate(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> dict[str, object]:
        message = await self._conversations.get_owned_message(session, user_id, companion_id, message_id)
        if message.conversation_id != conversation_id:
            raise ValueError("消息不属于该会话")
        if message.sender_type != SenderType.USER.value:
            return {"evaluated": 0, "ignored": 0, "skipped": True}
        rows = await self._memories.list_message_memories(session, user_id, companion_id, message_id)
        scoreable = [(memory, version) for memory, version in rows if memory.status not in _SKIPPABLE]
        if not scoreable:
            return {"evaluated": 0, "ignored": 0, "skipped": True}
        output = await self._adapter.complete_structured(
            ModelConfigKey.MEMORY,
            evaluation_messages(message.content, [_prompt_row(memory, version) for memory, version in scoreable]),
            EvaluationOutput,
            ModelCallScope(
                trace_id=uuid.uuid4(),
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                background_task_id=task_id,
            ),
        )
        known = {memory.id: memory for memory, _version in scoreable}
        applied: set[uuid.UUID] = set()
        scores: list[dict[str, object]] = []
        ignored = 0
        for item in output.evaluations:
            if item.memory_id not in known or item.memory_id in applied:
                ignored += 1
                continue
            memory = await self._memories.record_assessment(
                session,
                user_id,
                companion_id,
                item.memory_id,
                importance=importance_points(item.importance),
                confidence=item.confidence,
                stability=item.stability,
                relevance=item.relevance,
            )
            applied.add(item.memory_id)
            scores.append(_score_row(memory, item))
        ignored += len(known) - len(applied)
        logger.info("scored %s memories from message %s", len(applied), message_id)
        return {"evaluated": len(applied), "ignored": ignored, "skipped": False, "scores": scores}


def _prompt_row(memory: Memory, version: MemoryVersion) -> dict[str, object]:
    return {
        "id": str(memory.id),
        "category": memory.memory_category,
        "origin": memory.memory_origin,
        "is_inference": memory.is_inference,
        "content": version.content[:200],
        "summary": version.summary,
    }


def _score_row(memory: Memory, item: MemoryScore) -> dict[str, object]:
    score = quality_score(
        importance=item.importance,
        stability=item.stability,
        repetition=item.repetition,
        relatedness=item.relatedness,
        freshness=item.freshness,
    )
    return {
        "memory_id": str(memory.id),
        "importance": memory.importance,
        "stability": str(item.stability),
        "repetition": str(item.repetition),
        "relatedness": str(item.relatedness),
        "freshness": str(item.freshness),
        "confidence": str(item.confidence),
        "relevance": str(item.relevance),
        "score": str(score),
        "reason": item.reason,
        "status": memory.status,
    }


def _default_adapter() -> EvaluationModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
