import hashlib
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.identity.services.identity_service import IdentityService
from app.modules.memory.api.schemas import (
    CreateMemoryRelationRequest,
    CreateMemoryRequest,
    CreateMemoryVersionRequest,
    MemoryResponse,
    MemorySourceInput,
    MemorySourceResponse,
    MemoryVersionResponse,
    RecordEmbeddingRequest,
)
from app.modules.memory.domain.enums import (
    EmbeddingStatus,
    MemoryChangeType,
    MemoryOrigin,
    MemorySourceRole,
    MemorySourceType,
    MemoryStatus,
)
from app.modules.memory.repositories.memory_repository import MemoryRepository
from app.modules.memory.repositories.models import Memory, MemoryEmbedding, MemoryRelation, MemorySource, MemoryVersion
from app.shared.exceptions.errors import AppError, ConflictError, NotFoundError

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE = Decimal("0.500")


class MemoryService:
    def __init__(
        self,
        memories: MemoryRepository | None = None,
        identity: IdentityService | None = None,
        conversations: ConversationService | None = None,
    ) -> None:
        self._memories = memories or MemoryRepository()
        self._identity = identity or IdentityService()
        self._conversations = conversations or ConversationService()

    async def create_memory(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: CreateMemoryRequest,
    ) -> tuple[Memory, MemoryVersion, list[MemorySource]]:
        if session.in_transaction():
            created = await self._create_memory(session, user_id, companion_id, data)
        else:
            async with session.begin():
                created = await self._create_memory(session, user_id, companion_id, data)
        logger.info("created memory %s for companion %s", created[0].id, companion_id)
        return created

    async def has_message_evidence(self, session: AsyncSession, message_id: uuid.UUID) -> bool:
        return await self._memories.count_for_message(session, message_id) > 0

    async def _create_memory(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: CreateMemoryRequest,
    ) -> tuple[Memory, MemoryVersion, list[MemorySource]]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        self._require_inference_sources(data)
        memory_id = uuid.uuid4()
        version_id = uuid.uuid4()
        memory = Memory(
            id=memory_id,
            companion_id=companion_id,
            current_version_id=version_id,
            memory_type=data.memory_type.value,
            memory_category=data.memory_category,
            subject=data.subject,
            status=MemoryStatus.CANDIDATE.value,
            memory_origin=data.memory_origin.value,
            is_inference=data.is_inference,
            confidence=DEFAULT_CONFIDENCE,
        )
        version = MemoryVersion(
            id=version_id,
            memory_id=memory_id,
            version_number=1,
            content=data.content,
            structured_content=dict(data.structured_content),
            summary=data.summary,
            change_type=MemoryChangeType.CREATE.value,
            change_reason=data.change_reason,
            confidence_snapshot=memory.confidence,
        )
        await self._memories.add_memory(session, memory)
        await self._memories.add_version(session, version)
        sources = []
        for item in data.sources:
            sources.append(await self._add_source(session, user_id, companion_id, memory, item))
        return memory, version, sources

    async def get_memory(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> tuple[Memory, MemoryVersion, list[MemorySource]]:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require_current(session, companion_id, memory_id)

    async def list_memories(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[tuple[Memory, MemoryVersion, list[MemorySource]]]:
        if session.in_transaction():
            return await self._list_memories(session, user_id, companion_id)
        async with session.begin():
            return await self._list_memories(session, user_id, companion_id)

    async def _list_memories(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[tuple[Memory, MemoryVersion, list[MemorySource]]]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        memories = await self._memories.list_for_companion(session, companion_id)
        rows = []
        for memory in memories:
            version = await self._memories.get_version(session, memory.current_version_id)
            if version is None:
                continue
            sources = await self._memories.list_sources(session, memory.id)
            rows.append((memory, version, sources))
        return rows

    async def add_version(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        data: CreateMemoryVersionRequest,
    ) -> tuple[Memory, MemoryVersion, list[MemorySource]]:
        if session.in_transaction():
            updated = await self._add_version(session, user_id, companion_id, memory_id, data)
        else:
            async with session.begin():
                updated = await self._add_version(session, user_id, companion_id, memory_id, data)
        logger.info("added memory version %s for memory %s", updated[1].id, memory_id)
        return updated

    async def _add_version(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        data: CreateMemoryVersionRequest,
    ) -> tuple[Memory, MemoryVersion, list[MemorySource]]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        memory, current, sources = await self._require_current(session, companion_id, memory_id)
        version = MemoryVersion(
            memory_id=memory.id,
            version_number=current.version_number + 1,
            content=data.content,
            structured_content=dict(data.structured_content)
            if data.structured_content is not None
            else dict(current.structured_content),
            summary=data.summary if data.summary is not None else current.summary,
            change_type=data.change_type.value,
            change_reason=data.change_reason,
            confidence_snapshot=memory.confidence,
        )
        await self._memories.add_version(session, version)
        memory.current_version_id = version.id
        memory.updated_at = datetime.now(UTC)
        await session.flush()
        return memory, version, sources

    async def attach_message_source(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        message_id: uuid.UUID,
        role: MemorySourceRole,
    ) -> MemorySource:
        if session.in_transaction():
            return await self._attach_message_source(
                session, user_id, companion_id, memory_id, message_id, role
            )
        async with session.begin():
            return await self._attach_message_source(
                session, user_id, companion_id, memory_id, message_id, role
            )

    async def add_relation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        data: CreateMemoryRelationRequest,
    ) -> MemoryRelation:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            source = await self._require_memory(session, companion_id, memory_id)
            target = await self._require_memory(session, companion_id, data.target_memory_id)
            if source.id == target.id:
                raise ConflictError("记忆关系的两端不能相同")
            relation = await self._memories.add_relation(
                session,
                MemoryRelation(
                    source_memory_id=source.id,
                    target_memory_id=target.id,
                    relation_type=data.relation_type.value,
                    strength=data.strength,
                    description=data.description,
                ),
            )
        logger.info("related memory %s -> %s", source.id, target.id)
        return relation

    async def record_embedding(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        data: RecordEmbeddingRequest,
    ) -> MemoryEmbedding:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            _memory, version, _sources = await self._require_current(session, companion_id, memory_id)
            if data.status == EmbeddingStatus.COMPLETED and not data.embedding:
                raise AppError("完成状态必须带有向量")
            embedding = await self._memories.add_embedding(
                session,
                MemoryEmbedding(
                    memory_version_id=version.id,
                    embedding_model=data.embedding_model,
                    embedding=data.embedding,
                    content_hash=hashlib.sha256(version.content.encode("utf-8")).hexdigest(),
                    status=data.status.value,
                ),
            )
        logger.info("recorded embedding %s for version %s", embedding.id, version.id)
        return embedding

    async def list_message_memories(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> list[tuple[Memory, MemoryVersion]]:
        if session.in_transaction():
            return await self._list_message_memories(session, user_id, companion_id, message_id)
        async with session.begin():
            return await self._list_message_memories(session, user_id, companion_id, message_id)

    async def record_assessment(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        importance: int,
        confidence: Decimal,
        stability: Decimal,
        relevance: Decimal,
    ) -> Memory:
        if session.in_transaction():
            return await self._record_assessment(
                session,
                user_id,
                companion_id,
                memory_id,
                importance=importance,
                confidence=confidence,
                stability=stability,
                relevance=relevance,
            )
        async with session.begin():
            return await self._record_assessment(
                session,
                user_id,
                companion_id,
                memory_id,
                importance=importance,
                confidence=confidence,
                stability=stability,
                relevance=relevance,
            )

    async def delete_memory(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> None:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            await self._require_memory(session, companion_id, memory_id)
            await self._memories.delete_memory_graph(session, memory_id)
        logger.info("deleted memory %s", memory_id)

    async def _list_message_memories(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> list[tuple[Memory, MemoryVersion]]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        memories = await self._memories.list_for_message(session, companion_id, message_id)
        rows: list[tuple[Memory, MemoryVersion]] = []
        for memory in memories[:8]:
            version = await self._memories.get_version(session, memory.current_version_id)
            if version is None or version.memory_id != memory.id:
                continue
            rows.append((memory, version))
        return rows

    async def _record_assessment(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        importance: int,
        confidence: Decimal,
        stability: Decimal,
        relevance: Decimal,
    ) -> Memory:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        memory = await self._require_memory(session, companion_id, memory_id)
        memory.importance = importance
        memory.confidence = confidence
        memory.stability = stability
        memory.relevance = relevance
        memory.updated_at = datetime.now(UTC)
        await session.flush()
        return memory

    async def _attach_message_source(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        message_id: uuid.UUID,
        role: MemorySourceRole,
    ) -> MemorySource:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        memory = await self._require_memory(session, companion_id, memory_id)
        return await self._add_source(
            session,
            user_id,
            companion_id,
            memory,
            MemorySourceInput(
                source_type=MemorySourceType.MESSAGE,
                source_role=role,
                message_id=message_id,
            ),
        )

    async def _add_source(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory: Memory,
        item: MemorySourceInput,
    ) -> MemorySource:
        if item.source_type == MemorySourceType.MESSAGE:
            if item.message_id is None:
                raise AppError("消息来源必须指定消息")
            await self._conversations.get_owned_message(session, user_id, companion_id, item.message_id)
        elif item.source_type == MemorySourceType.MEMORY:
            if item.source_memory_id is None:
                raise AppError("记忆来源必须指定记忆")
            await self._require_memory(session, companion_id, item.source_memory_id)
            await self._assert_no_cycle(session, memory.id, item.source_memory_id)
        return await self._memories.add_source(
            session,
            MemorySource(
                memory_id=memory.id,
                message_id=item.message_id if item.source_type == MemorySourceType.MESSAGE else None,
                source_memory_id=item.source_memory_id if item.source_type == MemorySourceType.MEMORY else None,
                source_type=item.source_type.value,
                source_role=item.source_role.value,
                relevance_score=item.relevance_score,
            ),
        )

    async def _assert_no_cycle(
        self,
        session: AsyncSession,
        memory_id: uuid.UUID,
        source_memory_id: uuid.UUID,
    ) -> None:
        pending = [source_memory_id]
        seen: set[uuid.UUID] = set()
        while pending:
            current = pending.pop()
            if current == memory_id or current in seen:
                raise ConflictError("记忆来源不能形成循环")
            seen.add(current)
            pending.extend(await self._memories.list_memory_source_ids(session, current))

    async def _require_memory(self, session: AsyncSession, companion_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
        memory = await self._memories.get(session, memory_id)
        if memory is None or memory.companion_id != companion_id:
            raise NotFoundError("记忆不存在")
        return memory

    async def _require_current(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> tuple[Memory, MemoryVersion, list[MemorySource]]:
        memory = await self._require_memory(session, companion_id, memory_id)
        version = await self._memories.get_version(session, memory.current_version_id)
        if version is None or version.memory_id != memory.id:
            raise NotFoundError("记忆不存在")
        sources = await self._memories.list_sources(session, memory.id)
        return memory, version, sources

    def _require_inference_sources(self, data: CreateMemoryRequest) -> None:
        needs_evidence = data.is_inference or data.memory_origin == MemoryOrigin.AI_INFERENCE
        if needs_evidence and not data.sources:
            raise AppError("归纳认知必须保留来源依据")


def to_memory_response(
    memory: Memory,
    version: MemoryVersion,
    sources: list[MemorySource],
) -> MemoryResponse:
    return MemoryResponse(
        id=memory.id,
        companion_id=memory.companion_id,
        memory_type=memory.memory_type,
        memory_category=memory.memory_category,
        subject=memory.subject,
        status=memory.status,
        memory_origin=memory.memory_origin,
        is_inference=memory.is_inference,
        importance=memory.importance,
        confidence=memory.confidence,
        current_version_id=memory.current_version_id,
        current_version=MemoryVersionResponse(
            id=version.id,
            version_number=version.version_number,
            content=version.content,
            summary=version.summary,
            structured_content=version.structured_content,
            change_type=version.change_type,
            change_reason=version.change_reason,
            confidence_snapshot=version.confidence_snapshot,
            created_at=version.created_at,
        ),
        sources=[
            MemorySourceResponse(
                id=source.id,
                source_type=source.source_type,
                source_role=source.source_role,
                message_id=source.message_id,
                source_memory_id=source.source_memory_id,
                relevance_score=source.relevance_score,
            )
            for source in sources
        ],
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )
