import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.repositories.models import ChatTurn, Conversation, Message
from app.modules.identity.repositories.models import User


ACTIVE_STATUSES = ("pending", "running")


class ChatTurnRepository:
    async def get_for_message(self, session: AsyncSession, conversation_id: uuid.UUID, sequence: int) -> ChatTurn | None:
        return await session.scalar(select(ChatTurn).where(
            ChatTurn.conversation_id == conversation_id, ChatTurn.trigger_sequence == sequence,
        ))

    async def add(self, session: AsyncSession, thread: Conversation, message: Message) -> ChatTurn:
        turn = ChatTurn(conversation_id=thread.id, trigger_sequence=message.sequence_number, decision_id=uuid.uuid4())
        session.add(turn)
        await session.flush()
        return turn

    async def lock(self, session: AsyncSession, turn_id: uuid.UUID, conversation_id: uuid.UUID) -> ChatTurn | None:
        return await session.scalar(select(ChatTurn).where(
            ChatTurn.conversation_id == conversation_id, ChatTurn.id == turn_id,
        ).with_for_update())

    async def queued_companions(self, session: AsyncSession, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
        query = (
            select(Conversation.companion_id, Conversation.user_id)
            .join(ChatTurn, ChatTurn.conversation_id == Conversation.id)
            .join(User, User.id == Conversation.user_id)
            .where(User.status == "active", Conversation.is_managed, ChatTurn.status.in_(ACTIVE_STATUSES))
            .group_by(Conversation.companion_id, Conversation.user_id)
            .order_by(func.min(ChatTurn.created_at))
            .limit(limit)
        )
        return [(row.companion_id, row.user_id) for row in (await session.execute(query)).all()]

    async def next_turn(self, session: AsyncSession, thread: Conversation) -> tuple[ChatTurn, Message] | None:
        query = (
            select(ChatTurn, Message)
            .join(Message, (ChatTurn.conversation_id == Message.conversation_id)
                  & (ChatTurn.trigger_sequence == Message.sequence_number))
            .where(ChatTurn.conversation_id == thread.id, ChatTurn.status.in_(ACTIVE_STATUSES))
            .order_by(ChatTurn.trigger_sequence)
            .limit(1)
            .with_for_update(of=ChatTurn)
        )
        row = (await session.execute(query)).one_or_none()
        return (row[0], row[1]) if row else None

    async def recent(self, session: AsyncSession, conversation_id: uuid.UUID) -> list[ChatTurn]:
        return list(await session.scalars(
            select(ChatTurn).where(ChatTurn.conversation_id == conversation_id)
            .order_by(ChatTurn.updated_at.desc(), ChatTurn.trigger_sequence.desc()).limit(50),
        ))
