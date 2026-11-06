import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import CreateConversationRequest, CreateMessageRequest
from app.modules.conversation.domain.enums import (
    MESSAGE_STATUS_RECORDED,
    ContentType,
    ConversationStatus,
    MessageStatus,
    SenderType,
)
from app.modules.conversation.repositories.conversation_repository import ConversationRepository
from app.modules.conversation.repositories.message_repository import MessageRepository
from app.modules.conversation.repositories.models import Conversation, Message
from app.modules.identity.services.identity_service import IdentityService
from app.shared.exceptions.errors import NotFoundError

logger = logging.getLogger(__name__)


class AppendMessageResult:
    def __init__(self, message: Message, created: bool) -> None:
        self.message = message
        self.created = created


class ConversationService:
    def __init__(
        self,
        conversations: ConversationRepository | None = None,
        messages: MessageRepository | None = None,
        identity: IdentityService | None = None,
    ) -> None:
        self._conversations = conversations or ConversationRepository()
        self._messages = messages or MessageRepository()
        self._identity = identity or IdentityService()

    async def create_conversation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: CreateConversationRequest,
    ) -> Conversation:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            conversation = await self._conversations.add(
                session,
                Conversation(
                    user_id=user_id,
                    companion_id=companion_id,
                    title=data.title,
                    status=ConversationStatus.ACTIVE.value,
                    next_sequence_number=1,
                ),
            )
        logger.info("created conversation %s", conversation.id)
        return conversation

    async def list_conversations(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[Conversation]:
        if session.in_transaction():
            return await self._list_conversations(session, user_id, companion_id)
        async with session.begin():
            return await self._list_conversations(session, user_id, companion_id)

    async def _list_conversations(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[Conversation]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        return await self._conversations.list_for_scope(session, user_id, companion_id)

    async def archive_conversation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        async with session.begin():
            conversation = await self._require_conversation(session, user_id, companion_id, conversation_id)
            if conversation.status != ConversationStatus.ARCHIVED.value:
                conversation.status = ConversationStatus.ARCHIVED.value
                conversation.archived_at = datetime.now(UTC)
                conversation.updated_at = datetime.now(UTC)
                await session.flush()
        logger.info("archived conversation %s", conversation.id)
        return conversation

    async def append_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        data: CreateMessageRequest,
    ) -> AppendMessageResult:
        if session.in_transaction():
            result = await self._append_message(session, user_id, companion_id, conversation_id, data)
        else:
            async with session.begin():
                result = await self._append_message(session, user_id, companion_id, conversation_id, data)
        logger.info("recorded message %s in conversation %s", result.message.id, conversation_id)
        return result

    async def record_turn_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        message_id: uuid.UUID,
        content: str,
        status: MessageStatus,
    ) -> Message:
        data = CreateMessageRequest(sender_type=SenderType.COMPANION, content=content)
        if session.in_transaction():
            result = await self._append_message(
                session,
                user_id,
                companion_id,
                conversation_id,
                data,
                message_id=message_id,
                status=status.value,
            )
        else:
            async with session.begin():
                result = await self._append_message(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    data,
                    message_id=message_id,
                    status=status.value,
                )
        return result.message

    async def _append_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        data: CreateMessageRequest,
        *,
        message_id: uuid.UUID | None = None,
        status: str = MESSAGE_STATUS_RECORDED,
    ) -> AppendMessageResult:
        conversation = await self._require_conversation(
            session,
            user_id,
            companion_id,
            conversation_id,
            for_update=True,
        )
        if data.client_message_id is not None:
            existing = await self._messages.find_by_client_id(
                session,
                conversation.id,
                data.client_message_id,
            )
            if existing is not None:
                return AppendMessageResult(existing, created=False)
        sequence_number = conversation.next_sequence_number
        now = datetime.now(UTC)
        conversation.next_sequence_number = sequence_number + 1
        conversation.last_message_at = now
        conversation.updated_at = now
        message = await self._messages.add(
            session,
            Message(
                id=message_id if message_id is not None else uuid.uuid4(),
                conversation_id=conversation.id,
                sequence_number=sequence_number,
                client_message_id=data.client_message_id,
                sender_type=data.sender_type.value,
                content_type=ContentType.TEXT.value,
                content=data.content,
                status=status,
                metadata_=data.metadata.model_dump(),
            ),
        )
        return AppendMessageResult(message, created=True)

    async def get_owned_conversation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        if session.in_transaction():
            return await self._require_conversation(session, user_id, companion_id, conversation_id)
        async with session.begin():
            return await self._require_conversation(session, user_id, companion_id, conversation_id)

    async def get_owned_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> Message:
        if session.in_transaction():
            return await self._scoped_message(session, user_id, companion_id, message_id)
        async with session.begin():
            return await self._scoped_message(session, user_id, companion_id, message_id)

    async def _scoped_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> Message:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        message = await self._messages.get_for_companion(session, message_id, user_id, companion_id)
        if message is None:
            raise NotFoundError("消息不存在")
        return message

    async def list_messages(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> list[Message]:
        if session.in_transaction():
            return await self._list_messages(session, user_id, companion_id, conversation_id)
        async with session.begin():
            return await self._list_messages(session, user_id, companion_id, conversation_id)

    async def _list_messages(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> list[Message]:
        conversation = await self._require_conversation(session, user_id, companion_id, conversation_id)
        return await self._messages.list_for_conversation(session, conversation.id)

    async def _require_conversation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Conversation:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        conversation = await self._conversations.get_for_scope(
            session,
            conversation_id,
            user_id,
            companion_id,
            for_update=for_update,
        )
        if conversation is None:
            raise NotFoundError("会话不存在")
        return conversation
