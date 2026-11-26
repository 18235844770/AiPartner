import asyncio
import logging
import uuid
from contextlib import aclosing

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.modules.conversation.api.schemas import CreateMessageRequest
from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.repositories.chat_turn_repository import ChatTurnRepository
from app.modules.conversation.repositories.models import ChatTurn, Message
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.api.stream_schemas import MessageDelta, MessageStarted, TurnCompleted, encode_sse
from app.modules.dialogue.services.turn_service import DialogueTurnService
from app.modules.identity.services.companion_setup import CompanionSetupService
from app.shared.database.companion_lock import try_companion_lock
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import ConflictError, NotFoundError


logger = logging.getLogger(__name__)


def chat_channel(companion_id: uuid.UUID) -> str:
    return f"companion:chat:{companion_id}"


class AccountChatService:
    def __init__(self, engine: DialogueTurnService | None = None) -> None:
        self._conversations = ConversationService()
        self._companions = CompanionSetupService()
        self._turns = ChatTurnRepository()
        self._engine = engine

    async def send(
        self, session: AsyncSession, user_id: uuid.UUID, client_message_id: uuid.UUID, content: str,
    ) -> tuple[Message, ChatTurn]:
        async with session.begin():
            companion = await self._companions.get_ready(session, user_id)
            thread = await self._conversations.get_managed_thread(session, user_id, companion.id)
            appended = await self._conversations.append_message(
                session, user_id, companion.id, thread.id,
                CreateMessageRequest(sender_type=SenderType.USER, client_message_id=client_message_id, content=content),
            )
            turn = await self._turns.get_for_message(session, thread.id, appended.message.sequence_number)
            if turn is None:
                turn = await self._turns.add(session, thread, appended.message)
                appended.message.metadata_ = {**appended.message.metadata_, "turn_id": str(turn.id)}
            return appended.message, turn

    async def retry(self, session: AsyncSession, user_id: uuid.UUID, turn_id: uuid.UUID) -> ChatTurn:
        async with session.begin():
            companion = await self._companions.get_ready(session, user_id)
            thread = await self._conversations.get_managed_thread(session, user_id, companion.id)
            turn = await self._turns.lock(session, turn_id, thread.id)
            if turn is None:
                raise NotFoundError("回合不存在")
            if turn.status == "failed":
                turn.status = "pending"
                turn.attempt += 1
                turn.decision_id = uuid.uuid4()
            elif turn.status not in {"pending", "running"} or turn.attempt == 1:
                raise ConflictError("只有失败的回合可以重试")
            return turn

    async def recent_turns(self, session: AsyncSession, user_id: uuid.UUID, companion_id: uuid.UUID) -> list[ChatTurn]:
        async with session.begin():
            thread = await self._conversations.get_managed_thread(session, user_id, companion_id)
            return await self._turns.recent(session, thread.id)

    async def has_waiting_turn(self, session: AsyncSession, user_id: uuid.UUID, companion_id: uuid.UUID) -> bool:
        async with session.begin():
            thread = await self._conversations.get_managed_thread(session, user_id, companion_id)
            return await self._turns.next_turn(session, thread) is not None

    async def process_waiting(self, limit: int = 6) -> None:
        factory = get_session_factory()
        async with factory() as session, session.begin():
            targets = await self._turns.queued_companions(session, limit)
        await asyncio.gather(*(self.process_one(user_id, companion_id) for companion_id, user_id in targets))

    async def process_one(self, user_id: uuid.UUID, companion_id: uuid.UUID) -> None:
        factory = get_session_factory()
        async with try_companion_lock(companion_id) as acquired:
            if not acquired:
                return
            async with factory() as session:
                async with session.begin():
                    thread = await self._conversations.get_managed_thread(session, user_id, companion_id)
                    queued = await self._turns.next_turn(session, thread)
                    if queued is None:
                        return
                    turn, message = queued
                    turn.status = "running"
                turn_id, thread_id = turn.id, thread.id
                try:
                    status = await self._run(session, user_id, companion_id, turn, message)
                except Exception as exc:
                    logger.warning("account chat worker failed for turn %s (%s)", turn_id, type(exc).__name__)
                    await session.rollback()
                    status = "failed"
                async with session.begin():
                    locked = await self._turns.lock(session, turn_id, thread_id)
                    if locked is not None:
                        locked.status = status

    async def _run(
        self, session: AsyncSession, user_id: uuid.UUID, companion_id: uuid.UUID, turn: ChatTurn, message: Message,
    ) -> str:
        engine = self._engine or DialogueTurnService()
        stream = engine.iter_user_turn(
            session, user_id, companion_id, turn.conversation_id, message.content, message.client_message_id,
            managed_decision_id=turn.decision_id, public_turn_id=turn.id,
        )
        status = "failed"
        async with Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2) as redis:
            async with aclosing(stream):
                async for event in stream:
                    if isinstance(event, TurnCompleted):
                        status = event.outcome
                    elif isinstance(event, (MessageStarted, MessageDelta)):
                        public_event = event.model_copy(update={"turn_id": turn.id})
                        frame = encode_sse(public_event).replace(
                            f"id: {event.sequence}\n", f"id: turn:{turn.id}:{turn.attempt}:{event.sequence}\n", 1,
                        )
                        try:
                            await redis.publish(chat_channel(companion_id), frame)
                        except RedisError:
                            logger.debug("chat event delivery unavailable for companion %s", companion_id)
        return status
