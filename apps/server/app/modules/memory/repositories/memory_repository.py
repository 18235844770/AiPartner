import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
