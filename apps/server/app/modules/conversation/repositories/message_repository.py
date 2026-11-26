import uuid

from sqlalchemy import delete, or_, select
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

    async def list_page(
        self, session: AsyncSession, conversation_id: uuid.UUID, limit: int,
        before_sequence: int | None, after_sequence: int | None,
    ) -> tuple[list[Message], bool]:
        query = select(Message).where(Message.conversation_id == conversation_id)
        if before_sequence is not None:
            query = query.where(Message.sequence_number < before_sequence)
        if after_sequence is not None:
            query = query.where(Message.sequence_number > after_sequence).order_by(Message.sequence_number)
        else:
            query = query.order_by(Message.sequence_number.desc())
        rows = list(await session.scalars(query.limit(limit + 1)))
        page = rows[:limit]
        if after_sequence is None:
            page.reverse()
        return page, len(rows) > limit

    async def list_turn_context(
        self, session: AsyncSession, conversation_id: uuid.UUID, through_user_sequence: int, limit: int,
    ) -> list[Message]:
        messages = list(await session.scalars(
            select(Message).where(
                Message.conversation_id == conversation_id,
                or_(Message.sender_type != "user", Message.sequence_number <= through_user_sequence),
            ).order_by(Message.sequence_number.desc()).limit(limit),
        ))
        messages.reverse()
        return messages

    async def delete_for_conversation(self, session: AsyncSession, conversation_id: uuid.UUID) -> int:
        result = await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        return int(result.rowcount or 0)
