import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.repositories.models import Conversation, Message


class MessageRepository:
    async def add(self, session: AsyncSession, message: Message) -> Message:
        session.add(message)
        await session.flush()
        return message

    async def find_by_client_id(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        client_message_id: uuid.UUID,
    ) -> Message | None:
        result = await session.scalars(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_message_id == client_message_id,
            )
        )
        return result.one_or_none()

    async def get_for_companion(
        self,
        session: AsyncSession,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> Message | None:
        result = await session.scalars(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.id == message_id,
                Conversation.user_id == user_id,
                Conversation.companion_id == companion_id,
            )
        )
        return result.one_or_none()

    async def list_for_conversation(self, session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
        result = await session.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence_number)
        )
        return list(result.all())
