import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.memory.repositories.models import AttentionTopic, AttentionTopicMemory, WorkingMemory


class ContextRepository:
    async def get_working(self, session: AsyncSession, conversation_id: uuid.UUID) -> WorkingMemory | None:
        return await session.scalar(select(WorkingMemory).where(WorkingMemory.conversation_id == conversation_id))

    async def lock_working(self, session: AsyncSession, conversation_id: uuid.UUID) -> WorkingMemory | None:
        return await session.scalar(
            select(WorkingMemory).where(WorkingMemory.conversation_id == conversation_id).with_for_update()
        )

    async def add_working(self, session: AsyncSession, row: WorkingMemory) -> WorkingMemory:
        session.add(row)
        await session.flush()
        return row

    async def get_topic(self, session: AsyncSession, topic_id: uuid.UUID) -> AttentionTopic | None:
        return await session.get(AttentionTopic, topic_id)

    async def list_topics(self, session: AsyncSession, companion_id: uuid.UUID) -> list[AttentionTopic]:
        result = await session.scalars(
            select(AttentionTopic)
            .where(AttentionTopic.companion_id == companion_id)
            .order_by(AttentionTopic.updated_at.desc(), AttentionTopic.id)
        )
        return list(result.all())

    async def add_topic(self, session: AsyncSession, topic: AttentionTopic) -> AttentionTopic:
        session.add(topic)
        await session.flush()
        return topic

    async def find_link(
        self,
        session: AsyncSession,
        topic_id: uuid.UUID,
        memory_id: uuid.UUID,
    ) -> AttentionTopicMemory | None:
        return await session.scalar(
            select(AttentionTopicMemory).where(
                AttentionTopicMemory.topic_id == topic_id,
                AttentionTopicMemory.memory_id == memory_id,
            )
        )

    async def add_link(self, session: AsyncSession, link: AttentionTopicMemory) -> AttentionTopicMemory:
        session.add(link)
        await session.flush()
        return link

    async def list_memory_ids(self, session: AsyncSession, topic_id: uuid.UUID) -> list[uuid.UUID]:
        result = await session.scalars(
            select(AttentionTopicMemory.memory_id)
            .where(AttentionTopicMemory.topic_id == topic_id)
            .order_by(AttentionTopicMemory.created_at, AttentionTopicMemory.id)
        )
        return list(result.all())

    async def delete_links_for_memory(self, session: AsyncSession, memory_id: uuid.UUID) -> None:
        await session.execute(delete(AttentionTopicMemory).where(AttentionTopicMemory.memory_id == memory_id))
