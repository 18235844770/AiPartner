import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.services.proactive_schedule import schedule_proactive_event
from app.modules.identity.services.identity_service import IdentityService
from app.modules.memory.api.context_schemas import (
    AttentionTopicResponse,
    CreateAttentionTopicRequest,
    OpenThreadInput,
    SaveWorkingMemoryRequest,
    WorkingMemoryResponse,
)
from app.modules.memory.domain.enums import AttentionStatus, OpenThreadStatus
from app.modules.memory.domain.placement import next_topic_label, parse_topic_id
from app.modules.memory.repositories.context_repository import ContextRepository
from app.modules.memory.repositories.memory_repository import MemoryRepository
from app.modules.memory.repositories.models import AttentionTopic, AttentionTopicMemory, WorkingMemory
from app.shared.exceptions.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


class MemoryContextService:
    def __init__(
        self,
        contexts: ContextRepository | None = None,
        memories: MemoryRepository | None = None,
        identity: IdentityService | None = None,
        conversations: ConversationService | None = None,
    ) -> None:
        self._contexts = contexts or ContextRepository()
        self._memories = memories or MemoryRepository()
        self._identity = identity or IdentityService()
        self._conversations = conversations or ConversationService()

    async def get_working(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> WorkingMemory | None:
        if session.in_transaction():
            return await self._get_working(session, user_id, companion_id, conversation_id)
        async with session.begin():
            return await self._get_working(session, user_id, companion_id, conversation_id)

    async def working_for_turn(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> dict[str, object] | None:
        row = await self.get_working(session, user_id, companion_id, conversation_id)
        if row is None or not _usable(row, datetime.now(UTC)):
            return None
        return _working_context(row)

    async def save_working(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        data: SaveWorkingMemoryRequest,
    ) -> WorkingMemory:
        if session.in_transaction():
            saved = await self._save_working(session, user_id, companion_id, conversation_id, data)
        else:
            async with session.begin():
                saved = await self._save_working(session, user_id, companion_id, conversation_id, data)
        logger.info("saved working memory %s for conversation %s", saved.id, conversation_id)
        return saved

    async def record_topic_transition(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        transition: str | None,
        topic_id: str | None,
    ) -> WorkingMemory:
        if session.in_transaction():
            return await self._record_topic(session, user_id, companion_id, conversation_id, transition, topic_id)
        async with session.begin():
            return await self._record_topic(session, user_id, companion_id, conversation_id, transition, topic_id)

    async def add_open_thread(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str,
        message_id: uuid.UUID | None,
    ) -> WorkingMemory:
        thread = OpenThreadInput(title=title.strip()[:128], message_id=message_id)
        if session.in_transaction():
            return await self._add_open_thread(session, user_id, companion_id, conversation_id, thread)
        async with session.begin():
            return await self._add_open_thread(session, user_id, companion_id, conversation_id, thread)

    async def apply_summary(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        summary: str,
        threads: list[OpenThreadInput],
    ) -> WorkingMemory | None:
        if session.in_transaction():
            return await self._apply_summary(session, user_id, companion_id, conversation_id, summary, threads)
        async with session.begin():
            return await self._apply_summary(session, user_id, companion_id, conversation_id, summary, threads)

    async def list_attention_topics(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[AttentionTopicResponse]:
        if session.in_transaction():
            return await self._list_topics(session, user_id, companion_id)
        async with session.begin():
            return await self._list_topics(session, user_id, companion_id)

    async def active_attention_context(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[dict[str, object]]:
        topics = await self.list_attention_topics(session, user_id, companion_id)
        now = datetime.now(UTC)
        visible = [topic for topic in topics if topic.status == AttentionStatus.ACTIVE.value]
        return [_attention_context(topic, now) for topic in visible]

    async def create_attention_topic(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: CreateAttentionTopicRequest,
    ) -> AttentionTopicResponse:
        if session.in_transaction():
            created = await self._create_topic(session, user_id, companion_id, data)
        else:
            async with session.begin():
                created = await self._create_topic(session, user_id, companion_id, data)
        logger.info("created attention topic %s for companion %s", created.id, companion_id)
        return created

    async def set_attention_status(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        topic_id: uuid.UUID,
        status: AttentionStatus,
    ) -> AttentionTopicResponse:
        if session.in_transaction():
            return await self._set_status(session, user_id, companion_id, topic_id, status)
        async with session.begin():
            return await self._set_status(session, user_id, companion_id, topic_id, status)

    async def link_memory(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        topic_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> AttentionTopicResponse:
        if session.in_transaction():
            return await self._link_memory(session, user_id, companion_id, topic_id, memory_id)
        async with session.begin():
            return await self._link_memory(session, user_id, companion_id, topic_id, memory_id)

    async def _get_working(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> WorkingMemory | None:
        await self._conversations.get_owned_conversation(session, user_id, companion_id, conversation_id)
        row = await self._contexts.get_working(session, conversation_id)
        if row is None or row.companion_id != companion_id:
            return None
        return row

    async def _save_working(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        data: SaveWorkingMemoryRequest,
    ) -> WorkingMemory:
        await self._conversations.get_owned_conversation(session, user_id, companion_id, conversation_id)
        await self._require_topic(session, companion_id, data.attention_topic_id)
        row = await self._contexts.lock_working(session, conversation_id)
        now = datetime.now(UTC)
        threads = [item.model_dump(mode="json") for item in data.open_threads]
        archived_at = now if data.archived else None
        if row is None:
            if data.version not in {None, 1}:
                raise ConflictError("工作记忆版本不一致")
            return await self._contexts.add_working(
                session,
                WorkingMemory(
                    companion_id=companion_id,
                    conversation_id=conversation_id,
                    summary=data.summary,
                    current_topic=data.current_topic,
                    attention_topic_id=data.attention_topic_id,
                    open_threads=threads,
                    expires_at=data.expires_at,
                    archived_at=archived_at,
                    version=1,
                ),
            )
        if row.companion_id != companion_id:
            raise NotFoundError("工作记忆不存在")
        if data.version != row.version:
            raise ConflictError("工作记忆版本不一致")
        row.summary = data.summary
        row.current_topic = data.current_topic
        row.attention_topic_id = data.attention_topic_id
        row.open_threads = threads
        row.expires_at = data.expires_at
        row.archived_at = archived_at
        row.version += 1
        row.updated_at = now
        await session.flush()
        return row

    async def _record_topic(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        transition: str | None,
        topic_id: str | None,
    ) -> WorkingMemory:
        await self._conversations.get_owned_conversation(session, user_id, companion_id, conversation_id)
        row = await self._contexts.lock_working(session, conversation_id)
        now = datetime.now(UTC)
        current = None if row is None else row.current_topic
        closing = transition == "close"
        label = next_topic_label(current, transition, topic_id)
        linked = None if closing else await self._matching_topic(session, companion_id, topic_id)
        if row is None:
            row = await self._contexts.add_working(
                session,
                WorkingMemory(
                    companion_id=companion_id,
                    conversation_id=conversation_id,
                    current_topic=label,
                    attention_topic_id=linked.id if linked is not None else None,
                    open_threads=[],
                    version=1,
                ),
            )
        else:
            row.current_topic = label
            row.archived_at = None
            if closing:
                row.attention_topic_id = None
            elif linked is not None:
                row.attention_topic_id = linked.id
            row.version += 1
            row.updated_at = now
            await session.flush()
        discussed_id = None if closing else row.attention_topic_id
        discussed = linked if linked is not None else await self._topic_or_none(session, discussed_id)
        if discussed is not None and discussed.companion_id == companion_id:
            discussed.last_discussed_at = now
            discussed.updated_at = now
            await session.flush()
        return row

    async def _add_open_thread(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        thread: OpenThreadInput,
    ) -> WorkingMemory:
        await self._conversations.get_owned_conversation(session, user_id, companion_id, conversation_id)
        row = await self._contexts.lock_working(session, conversation_id)
        payload = thread.model_dump(mode="json")
        now = datetime.now(UTC)
        if row is None:
            return await self._contexts.add_working(
                session,
                WorkingMemory(
                    companion_id=companion_id,
                    conversation_id=conversation_id,
                    open_threads=[payload],
                    version=1,
                ),
            )
        if row.companion_id != companion_id:
            raise NotFoundError("工作记忆不存在")
        existing = list(row.open_threads)
        if not any(item.get("title") == thread.title and item.get("status") == "open" for item in existing):
            existing.append(payload)
            row.open_threads = existing
        row.archived_at = None
        row.version += 1
        row.updated_at = now
        await session.flush()
        return row

    async def _apply_summary(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        summary: str,
        threads: list[OpenThreadInput],
    ) -> WorkingMemory | None:
        await self._conversations.get_owned_conversation(session, user_id, companion_id, conversation_id)
        row = await self._contexts.lock_working(session, conversation_id)
        now = datetime.now(UTC)
        if row is not None and row.archived_at is not None:
            return None
        merged = _merge_threads([] if row is None else list(row.open_threads), threads)
        if row is None:
            return await self._contexts.add_working(
                session,
                WorkingMemory(
                    companion_id=companion_id,
                    conversation_id=conversation_id,
                    summary=summary,
                    open_threads=merged,
                    version=1,
                ),
            )
        if row.companion_id != companion_id:
            raise NotFoundError("工作记忆不存在")
        row.summary = summary
        row.open_threads = merged
        row.version += 1
        row.updated_at = now
        await session.flush()
        return row

    async def _list_topics(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[AttentionTopicResponse]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        topics = await self._contexts.list_topics(session, companion_id)
        responses: list[AttentionTopicResponse] = []
        for topic in topics:
            memory_ids = await self._contexts.list_memory_ids(session, topic.id)
            responses.append(_topic_response(topic, memory_ids))
        return responses

    async def _create_topic(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: CreateAttentionTopicRequest,
    ) -> AttentionTopicResponse:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        topic = await self._contexts.add_topic(
            session,
            AttentionTopic(
                companion_id=companion_id,
                title=data.title,
                description=data.description,
                origin_type=data.origin_type.value,
                status=AttentionStatus.ACTIVE.value,
                interest_score=data.interest_score,
                next_review_at=data.next_review_at,
            ),
        )
        await schedule_proactive_event(
            session,
            user_id=user_id,
            companion_id=companion_id,
            event_key=f"topic:{topic.id}:created",
        )
        return _topic_response(topic, [])

    async def _set_status(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        topic_id: uuid.UUID,
        status: AttentionStatus,
    ) -> AttentionTopicResponse:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        topic = await self._require_owned_topic(session, companion_id, topic_id)
        previous = topic.status
        topic.status = status.value
        topic.updated_at = datetime.now(UTC)
        await session.flush()
        if status == AttentionStatus.ACTIVE and previous != AttentionStatus.ACTIVE.value:
            await schedule_proactive_event(
                session,
                user_id=user_id,
                companion_id=companion_id,
                event_key=f"topic:{topic.id}:resume:{previous}",
            )
        memory_ids = await self._contexts.list_memory_ids(session, topic.id)
        return _topic_response(topic, memory_ids)

    async def _link_memory(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        topic_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> AttentionTopicResponse:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        topic = await self._require_owned_topic(session, companion_id, topic_id)
        memory = await self._memories.get(session, memory_id)
        if memory is None or memory.companion_id != companion_id:
            raise NotFoundError("记忆不存在")
        existing = await self._contexts.find_link(session, topic_id, memory_id)
        if existing is None:
            await self._contexts.add_link(
                session,
                AttentionTopicMemory(companion_id=companion_id, topic_id=topic_id, memory_id=memory_id),
            )
        memory_ids = await self._contexts.list_memory_ids(session, topic.id)
        return _topic_response(topic, memory_ids)

    async def _require_topic(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        topic_id: uuid.UUID | None,
    ) -> None:
        if topic_id is None:
            return
        await self._require_owned_topic(session, companion_id, topic_id)

    async def _require_owned_topic(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        topic_id: uuid.UUID,
    ) -> AttentionTopic:
        topic = await self._contexts.get_topic(session, topic_id)
        if topic is None or topic.companion_id != companion_id:
            raise NotFoundError("关注主题不存在")
        return topic

    async def _matching_topic(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        topic_id: str | None,
    ) -> AttentionTopic | None:
        parsed = parse_topic_id(topic_id)
        if parsed is None:
            return None
        topic = await self._contexts.get_topic(session, parsed)
        if topic is None or topic.companion_id != companion_id:
            return None
        return topic

    async def _topic_or_none(self, session: AsyncSession, topic_id: uuid.UUID | None) -> AttentionTopic | None:
        if topic_id is None:
            return None
        return await self._contexts.get_topic(session, topic_id)


def to_working_response(row: WorkingMemory) -> WorkingMemoryResponse:
    return WorkingMemoryResponse(
        id=row.id,
        companion_id=row.companion_id,
        conversation_id=row.conversation_id,
        summary=row.summary,
        current_topic=row.current_topic,
        attention_topic_id=row.attention_topic_id,
        open_threads=list(row.open_threads),
        expires_at=row.expires_at,
        archived_at=row.archived_at,
        version=row.version,
    )


def _merge_threads(existing: list[object], updates: list[OpenThreadInput]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    index: dict[str, int] = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        copied = dict(item)
        rows.append(copied)
        index[title] = len(rows) - 1
    for update in updates:
        position = index.get(update.title)
        if position is not None:
            rows[position]["status"] = update.status.value
            continue
        if update.status != OpenThreadStatus.OPEN:
            continue
        rows.append(update.model_dump(mode="json"))
        index[update.title] = len(rows) - 1
    return rows


def _usable(row: WorkingMemory, now: datetime) -> bool:
    if row.archived_at is not None:
        return False
    return row.expires_at is None or row.expires_at >= now


def _working_context(row: WorkingMemory) -> dict[str, object]:
    return {
        "summary": row.summary,
        "current_topic": row.current_topic,
        "open_threads": list(row.open_threads),
        "attention_topic_id": str(row.attention_topic_id) if row.attention_topic_id is not None else None,
    }


def _attention_context(topic: AttentionTopicResponse, now: datetime) -> dict[str, object]:
    due = topic.next_review_at is None or topic.next_review_at <= now
    return {
        "id": str(topic.id),
        "title": topic.title,
        "description": topic.description,
        "origin_type": topic.origin_type,
        "interest_score": f"{topic.interest_score.quantize(Decimal('0.001'))}",
        "review_due": due,
    }


def _topic_response(topic: AttentionTopic, memory_ids: list[uuid.UUID]) -> AttentionTopicResponse:
    return AttentionTopicResponse(
        id=topic.id,
        companion_id=topic.companion_id,
        title=topic.title,
        description=topic.description,
        origin_type=topic.origin_type,
        status=topic.status,
        interest_score=topic.interest_score,
        last_discussed_at=topic.last_discussed_at,
        next_review_at=topic.next_review_at,
        memory_ids=memory_ids,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )
