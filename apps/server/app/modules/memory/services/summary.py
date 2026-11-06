"""用最近的对话更新工作记忆摘要。失败时不改已有的工作记忆。"""

import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.domain.enums import MessageStatus, SenderType
from app.modules.conversation.repositories.models import Message
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.infrastructure.domain.enums import ModelConfigKey
from app.modules.memory.api.context_schemas import OpenThreadInput
from app.modules.memory.domain.summary import SummaryOutput, SummaryThread, summary_messages
from app.modules.memory.repositories.models import WorkingMemory
from app.modules.memory.services.context_service import MemoryContextService
from app.modules.model_adapter.domain.messages import ChatMessage
from app.modules.model_adapter.services.model_adapter import ModelCallScope

logger = logging.getLogger(__name__)

_VISIBLE = {MessageStatus.RECORDED.value, MessageStatus.COMPLETED.value}
_SPEAKERS = {SenderType.USER.value, SenderType.COMPANION.value}
_WINDOW = 12


class SummaryModel(Protocol):
    async def complete_structured(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        result_type: type[SummaryOutput],
        scope: ModelCallScope,
    ) -> SummaryOutput: ...


class MemorySummaryService:
    def __init__(
        self,
        contexts: MemoryContextService | None = None,
        conversations: ConversationService | None = None,
        adapter: SummaryModel | None = None,
    ) -> None:
        self._contexts = contexts or MemoryContextService()
        self._conversations = conversations or ConversationService()
        self._adapter = adapter if adapter is not None else _default_adapter()

    async def summarize(
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
            return await self._summarize(
                session,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                message_id=message_id,
                task_id=task_id,
            )
        async with session.begin():
            return await self._summarize(
                session,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                message_id=message_id,
                task_id=task_id,
            )

    async def _summarize(
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
        current = await self._contexts.get_working(session, user_id, companion_id, conversation_id)
        if current is not None and current.archived_at is not None:
            return {"summarized": False, "reason": "archived"}
        visible = _recent_lines(await self._conversations.list_messages(session, user_id, companion_id, conversation_id))
        if not visible:
            return {"summarized": False, "reason": "no_messages"}
        output = await self._adapter.complete_structured(
            ModelConfigKey.MEMORY,
            summary_messages(_prompt_context(current, visible)),
            SummaryOutput,
            ModelCallScope(
                trace_id=uuid.uuid4(),
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                background_task_id=task_id,
            ),
        )
        saved = await self._contexts.apply_summary(
            session,
            user_id,
            companion_id,
            conversation_id,
            output.summary,
            [_thread_input(item) for item in output.open_threads],
        )
        if saved is None:
            return {"summarized": False, "reason": "archived"}
        logger.info("summarized working memory %s for conversation %s", saved.id, conversation_id)
        return {"summarized": True, "version": saved.version}


def _recent_lines(messages: list[Message]) -> list[dict[str, str]]:
    visible = [
        message
        for message in messages
        if message.status in _VISIBLE and message.sender_type in _SPEAKERS and message.content.strip()
    ]
    return [{"sender": message.sender_type, "content": message.content.strip()} for message in visible[-_WINDOW:]]


def _prompt_context(current: WorkingMemory | None, messages: list[dict[str, str]]) -> dict[str, object]:
    threads = [] if current is None else list(current.open_threads)
    return {
        "current_topic": None if current is None else current.current_topic,
        "summary": None if current is None else current.summary,
        "open_threads": [
            {"title": item.get("title"), "status": item.get("status")}
            for item in threads
            if isinstance(item, dict) and isinstance(item.get("title"), str)
        ],
        "messages": messages,
    }


def _thread_input(item: SummaryThread) -> OpenThreadInput:
    return OpenThreadInput(title=item.title, status=item.status)


def _default_adapter() -> SummaryModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
