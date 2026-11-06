"""为一条用户消息涉及的记忆补上关联。失败不回滚已经保存的记忆。"""

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.services.proactive_schedule import schedule_proactive_event
from app.modules.infrastructure.domain.enums import ModelConfigKey
from app.modules.memory.api.schemas import CreateMemoryRelationRequest
from app.modules.memory.domain.enums import MemoryStatus
from app.modules.memory.domain.relation import RelationOutput, RelationProposal, relation_messages
from app.modules.memory.repositories.memory_repository import MemoryRepository
from app.modules.memory.repositories.models import Memory, MemoryVersion
from app.modules.memory.services.memory_service import MemoryService
from app.modules.model_adapter.domain.messages import ChatMessage
from app.modules.model_adapter.services.model_adapter import ModelCallScope

logger = logging.getLogger(__name__)

_HIDDEN = {MemoryStatus.ARCHIVED.value, MemoryStatus.REJECTED.value}
_CONTEXT_LIMIT = 20


class RelationModel(Protocol):
    async def complete_structured(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        result_type: type[RelationOutput],
        scope: ModelCallScope,
    ) -> RelationOutput: ...


class MemoryRelationService:
    def __init__(
        self,
        memories: MemoryService | None = None,
        conversations: ConversationService | None = None,
        repository: MemoryRepository | None = None,
        adapter: RelationModel | None = None,
    ) -> None:
        self._memories = memories or MemoryService()
        self._conversations = conversations or ConversationService()
        self._repository = repository or MemoryRepository()
        self._adapter = adapter if adapter is not None else _default_adapter()

    async def relate(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> dict[str, object]:
        if session.in_transaction():
            return await self._relate(
                session,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                message_id=message_id,
                task_id=task_id,
            )
        async with session.begin():
            return await self._relate(
                session,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                message_id=message_id,
                task_id=task_id,
            )

    async def _relate(
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
            return {"linked": 0, "ignored": 0, "skipped": True}
        current = await self._memories.list_message_memories(session, user_id, companion_id, message_id)
        current_rows = [(memory, version) for memory, version in current if memory.status not in _HIDDEN]
        current_ids = {memory.id for memory, _version in current_rows}
        if not current_ids:
            return {"linked": 0, "ignored": 0, "skipped": True}
        context = await self._context(session, user_id, companion_id, current_rows)
        if len(context) < 2:
            return {"linked": 0, "ignored": 0, "skipped": True}
        output = await self._adapter.complete_structured(
            ModelConfigKey.MEMORY,
            relation_messages(message.content, [_prompt_row(memory, version, memory.id in current_ids) for memory, version in context]),
            RelationOutput,
            ModelCallScope(
                trace_id=uuid.uuid4(),
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                background_task_id=task_id,
            ),
        )
        known = {memory.id for memory, _version in context}
        linked = 0
        ignored = 0
        seen: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
        for item in output.relations:
            if not _acceptable(item, known, current_ids) or (item.source_memory_id, item.target_memory_id, item.relation_type.value) in seen:
                ignored += 1
                continue
            seen.add((item.source_memory_id, item.target_memory_id, item.relation_type.value))
            existing = await self._repository.find_relation(
                session,
                item.source_memory_id,
                item.target_memory_id,
                item.relation_type.value,
            )
            if existing is not None:
                ignored += 1
                continue
            await self._memories.add_relation(
                session,
                user_id,
                companion_id,
                item.source_memory_id,
                CreateMemoryRelationRequest(
                    target_memory_id=item.target_memory_id,
                    relation_type=item.relation_type,
                    strength=item.strength,
                    description=item.description,
                ),
            )
            linked += 1
        if linked:
            await schedule_proactive_event(
                session,
                user_id=user_id,
                companion_id=companion_id,
                event_key=f"relation:{message_id}",
            )
        logger.info("linked %s memories from message %s", linked, message_id)
        return {"linked": linked, "ignored": ignored, "skipped": False}

    async def _context(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        current_rows: list[tuple[Memory, MemoryVersion]],
    ) -> list[tuple[Memory, MemoryVersion]]:
        chosen = list(current_rows)
        seen = {memory.id for memory, _version in chosen}
        rows = await self._memories.list_memories(session, user_id, companion_id)
        for memory, version, _sources in rows:
            if memory.id in seen or memory.status in _HIDDEN:
                continue
            chosen.append((memory, version))
            seen.add(memory.id)
            if len(chosen) >= _CONTEXT_LIMIT:
                break
        return chosen[:_CONTEXT_LIMIT]


def _acceptable(item: RelationProposal, known: set[uuid.UUID], current_ids: set[uuid.UUID]) -> bool:
    if item.source_memory_id == item.target_memory_id:
        return False
    if item.source_memory_id not in known or item.target_memory_id not in known:
        return False
    return item.source_memory_id in current_ids or item.target_memory_id in current_ids


def _prompt_row(memory: Memory, version: MemoryVersion, from_message: bool) -> dict[str, object]:
    return {
        "id": str(memory.id),
        "category": memory.memory_category,
        "memory_type": memory.memory_type,
        "content": version.content[:200],
        "summary": version.summary,
        "from_message": from_message,
    }


def _default_adapter() -> RelationModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
