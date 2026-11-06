import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.memory.domain.enums import EmbeddingStatus
from app.modules.memory.repositories.context_repository import ContextRepository
from app.modules.memory.repositories.models import (
    Memory,
    MemoryEmbedding,
    MemoryRelation,
    MemorySource,
    MemoryVersion,
)


class MemoryRepository:
    async def add_memory(self, session: AsyncSession, memory: Memory) -> Memory:
        session.add(memory)
        await session.flush()
        return memory

    async def add_version(self, session: AsyncSession, version: MemoryVersion) -> MemoryVersion:
        session.add(version)
        await session.flush()
        return version

    async def add_source(self, session: AsyncSession, source: MemorySource) -> MemorySource:
        session.add(source)
        await session.flush()
        return source

    async def add_relation(self, session: AsyncSession, relation: MemoryRelation) -> MemoryRelation:
        session.add(relation)
        await session.flush()
        return relation

    async def add_embedding(self, session: AsyncSession, embedding: MemoryEmbedding) -> MemoryEmbedding:
        session.add(embedding)
        await session.flush()
        return embedding

    async def get_embedding(
        self,
        session: AsyncSession,
        version_id: uuid.UUID,
        embedding_model: str,
    ) -> MemoryEmbedding | None:
        result = await session.scalars(
            select(MemoryEmbedding).where(
                MemoryEmbedding.memory_version_id == version_id,
                MemoryEmbedding.embedding_model == embedding_model,
            )
        )
        return result.one_or_none()

    async def list_completed_embeddings(
        self,
        session: AsyncSession,
        version_ids: list[uuid.UUID],
    ) -> list[MemoryEmbedding]:
        if not version_ids:
            return []
        result = await session.scalars(
            select(MemoryEmbedding).where(
                MemoryEmbedding.memory_version_id.in_(version_ids),
                MemoryEmbedding.status == EmbeddingStatus.COMPLETED.value,
                MemoryEmbedding.embedding.is_not(None),
            )
        )
        return list(result.all())

    async def list_relation_pairs(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        source_memory = aliased(Memory)
        target_memory = aliased(Memory)
        statement = (
            select(MemoryRelation.source_memory_id, MemoryRelation.target_memory_id)
            .join(source_memory, source_memory.id == MemoryRelation.source_memory_id)
            .join(target_memory, target_memory.id == MemoryRelation.target_memory_id)
            .where(
                source_memory.companion_id == companion_id,
                target_memory.companion_id == companion_id,
            )
        )
        rows = (await session.execute(statement)).all()
        return [(row[0], row[1]) for row in rows]

    async def find_relation(
        self,
        session: AsyncSession,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
    ) -> MemoryRelation | None:
        result = await session.scalars(
            select(MemoryRelation).where(
                MemoryRelation.source_memory_id == source_id,
                MemoryRelation.target_memory_id == target_id,
                MemoryRelation.relation_type == relation_type,
            )
        )
        return result.one_or_none()

    async def get(self, session: AsyncSession, memory_id: uuid.UUID) -> Memory | None:
        return await session.get(Memory, memory_id)

    async def get_version(self, session: AsyncSession, version_id: uuid.UUID) -> MemoryVersion | None:
        return await session.get(MemoryVersion, version_id)

    async def list_for_companion(self, session: AsyncSession, companion_id: uuid.UUID) -> list[Memory]:
        result = await session.scalars(
            select(Memory).where(Memory.companion_id == companion_id).order_by(Memory.updated_at.desc())
        )
        return list(result.all())

    async def list_for_message(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> list[Memory]:
        result = await session.scalars(
            select(Memory)
            .join(MemorySource, MemorySource.memory_id == Memory.id)
            .where(Memory.companion_id == companion_id, MemorySource.message_id == message_id)
            .order_by(Memory.created_at, Memory.id)
        )
        rows: list[Memory] = []
        seen: set[uuid.UUID] = set()
        for memory in result.all():
            if memory.id in seen:
                continue
            seen.add(memory.id)
            rows.append(memory)
        return rows

    async def count_for_message(self, session: AsyncSession, message_id: uuid.UUID) -> int:
        result = await session.scalar(
            select(func.count()).select_from(MemorySource).where(MemorySource.message_id == message_id)
        )
        return int(result or 0)

    async def list_sources(self, session: AsyncSession, memory_id: uuid.UUID) -> list[MemorySource]:
        result = await session.scalars(
            select(MemorySource).where(MemorySource.memory_id == memory_id).order_by(MemorySource.created_at)
        )
        return list(result.all())

    async def list_memory_source_ids(self, session: AsyncSession, memory_id: uuid.UUID) -> list[uuid.UUID]:
        result = await session.scalars(
            select(MemorySource.source_memory_id).where(
                MemorySource.memory_id == memory_id,
                MemorySource.source_memory_id.is_not(None),
            )
        )
        return [item for item in result.all() if item is not None]

    async def delete_memory_graph(self, session: AsyncSession, memory_id: uuid.UUID) -> None:
        await ContextRepository().delete_links_for_memory(session, memory_id)
        version_ids = select(MemoryVersion.id).where(MemoryVersion.memory_id == memory_id)
        await session.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_version_id.in_(version_ids)))
        await session.execute(
            delete(MemorySource).where(
                or_(MemorySource.memory_id == memory_id, MemorySource.source_memory_id == memory_id)
            )
        )
        await session.execute(
            delete(MemoryRelation).where(
                or_(MemoryRelation.source_memory_id == memory_id, MemoryRelation.target_memory_id == memory_id)
            )
        )
        await session.execute(delete(MemoryVersion).where(MemoryVersion.memory_id == memory_id))
        await session.execute(delete(Memory).where(Memory.id == memory_id))
        await session.flush()
