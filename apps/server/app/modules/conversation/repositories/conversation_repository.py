import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.repositories.models import Conversation


class ConversationRepository:
    async def add(self, session: AsyncSession, conversation: Conversation) -> Conversation:
        session.add(conversation)
        await session.flush()
        return conversation

    async def get_for_scope(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.companion_id == companion_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.scalars(statement)
        return result.one_or_none()

    async def list_for_scope(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[Conversation]:
        result = await session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.companion_id == companion_id)
            .order_by(Conversation.created_at)
        )
        return list(result.all())
