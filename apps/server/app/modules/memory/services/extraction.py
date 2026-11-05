import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType, ModelConfigKey
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.memory.api.schemas import CreateMemoryRequest, CreateMemoryVersionRequest, MemorySourceInput
from app.modules.memory.domain.enums import (
    MemoryChangeType,
    MemoryOrigin,
    MemorySourceRole,
    MemorySourceType,
    MemoryStatus,
    MemoryType,
)
from app.modules.memory.domain.extraction import (
    ExtractedMemory,
    ExtractionCategory,
    ExtractionOutput,
    MemoryWriteAction,
    extraction_messages,
)
from app.modules.memory.services.memory_service import MemoryService
from app.modules.model_adapter.domain.messages import ChatMessage
from app.modules.model_adapter.services.model_adapter import ModelCallScope

logger = logging.getLogger(__name__)


class ExtractionModel(Protocol):
    async def complete_structured(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        result_type: type[ExtractionOutput],
        scope: ModelCallScope,
    ) -> ExtractionOutput: ...


class MemoryExtractionService:
    def __init__(
        self,
        memories: MemoryService | None = None,
        conversations: ConversationService | None = None,
        adapter: ExtractionModel | None = None,
        tasks: BackgroundTaskService | None = None,
    ) -> None:
        self._memories = memories or MemoryService()
        self._conversations = conversations or ConversationService()
        self._adapter = adapter if adapter is not None else _default_adapter()
        self._tasks = tasks or BackgroundTaskService()

    async def extract(
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
            return {"created": 0, "supplemented": 0, "corrected": 0, "ignored": 0, "skipped": True}
        if await self._memories.has_message_evidence(session, message_id):
            return {"created": 0, "supplemented": 0, "corrected": 0, "ignored": 0, "skipped": True}
        existing = await self._existing(session, user_id, companion_id)
        output = await self._adapter.complete_structured(
            ModelConfigKey.MEMORY,
            extraction_messages(message.content, existing),
            ExtractionOutput,
            ModelCallScope(
                trace_id=uuid.uuid4(),
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                background_task_id=task_id,
            ),
        )
        counts = {"created": 0, "supplemented": 0, "corrected": 0, "ignored": 0}
        known = {item["id"] for item in existing}
        for item in output.memories:
            applied = await self._apply(session, user_id, companion_id, message_id, item, known)
            counts[applied] += 1
        written = counts["created"] + counts["supplemented"] + counts["corrected"]
        if written:
            await self._schedule_evaluation(session, user_id, companion_id, conversation_id, message_id)
        logger.info("extracted memories from message %s: %s", message_id, counts)
        return {**counts, "skipped": False}

    async def _schedule_evaluation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> None:
        await self._tasks.create(
            session,
            CreateBackgroundTaskRequest(
                user_id=user_id,
                companion_id=companion_id,
                task_type=BackgroundTaskType.MEMORY_EVALUATE,
                task_key=f"memory-evaluate:{message_id}",
                queue_name="memory",
                payload={
                    "user_id": str(user_id),
                    "message_id": str(message_id),
                    "conversation_id": str(conversation_id),
                },
                max_retries=2,
                scheduled_at=datetime.now(UTC),
            ),
        )

    async def _existing(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[dict[str, object]]:
        rows = await self._memories.list_memories(session, user_id, companion_id)
        visible = [
            (memory, version)
            for memory, version, _sources in rows
            if memory.status not in {MemoryStatus.ARCHIVED.value, MemoryStatus.REJECTED.value}
        ]
        return [
            {
                "id": str(memory.id),
                "category": memory.memory_category,
                "content": version.content[:200],
                "summary": version.summary,
            }
            for memory, version in visible[:20]
        ]

    async def _apply(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
        item: ExtractedMemory,
        known: set[str],
    ) -> str:
        target = str(item.target_memory_id) if item.target_memory_id is not None else None
        if item.action == MemoryWriteAction.IGNORE or (
            item.action in {MemoryWriteAction.SUPPLEMENT, MemoryWriteAction.CORRECT} and target not in known
        ):
            return "ignored"
        if item.action == MemoryWriteAction.SUPPLEMENT:
            await self._revise(
                session,
                user_id,
                companion_id,
                message_id,
                item,
                MemoryChangeType.SUPPLEMENT,
                MemorySourceRole.EVIDENCE,
            )
            return "supplemented"
        if item.action == MemoryWriteAction.CORRECT:
            await self._revise(
                session,
                user_id,
                companion_id,
                message_id,
                item,
                MemoryChangeType.CORRECT,
                MemorySourceRole.CORRECTION,
            )
            return "corrected"
        await self._memories.create_memory(session, user_id, companion_id, _candidate(message_id, item))
        return "created"

    async def _revise(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
        item: ExtractedMemory,
        change_type: MemoryChangeType,
        role: MemorySourceRole,
    ) -> None:
        assert item.target_memory_id is not None
        await self._memories.add_version(
            session,
            user_id,
            companion_id,
            item.target_memory_id,
            CreateMemoryVersionRequest(
                change_type=change_type,
                change_reason=item.reason or "根据后续用户消息更新候选记忆",
                content=item.content,
                summary=item.summary,
                structured_content={"category": item.category.value, "explicit": item.explicit, "action": item.action.value},
            ),
        )
        await self._memories.attach_message_source(
            session,
            user_id,
            companion_id,
            item.target_memory_id,
            message_id,
            role,
        )


def _candidate(message_id: uuid.UUID, item: ExtractedMemory) -> CreateMemoryRequest:
    memory_type = item.memory_type
    if item.category == ExtractionCategory.EMOTION and memory_type != MemoryType.EPISODIC:
        memory_type = MemoryType.EPISODIC
    explicit = item.explicit
    return CreateMemoryRequest(
        memory_type=memory_type,
        memory_category=item.category.value,
        subject=item.subject,
        memory_origin=MemoryOrigin.USER_EXPLICIT if explicit else MemoryOrigin.AI_INFERENCE,
        is_inference=not explicit,
        content=item.content,
        summary=item.summary,
        structured_content={"category": item.category.value, "explicit": explicit},
        change_reason="从用户消息提取的候选记忆",
        sources=[
            MemorySourceInput(
                source_type=MemorySourceType.MESSAGE,
                source_role=MemorySourceRole.EVIDENCE,
                message_id=message_id,
            )
        ],
    )


def _default_adapter() -> ExtractionModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
