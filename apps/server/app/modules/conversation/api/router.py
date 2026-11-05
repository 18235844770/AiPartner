import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    MessageResponse,
)
from app.modules.conversation.repositories.models import Conversation, Message
from app.modules.conversation.services.conversation_service import ConversationService
from app.shared.database.session import get_session

router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}/conversations",
    tags=["conversations"],
)
conversation_service = ConversationService()


def to_conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        user_id=conversation.user_id,
        companion_id=conversation.companion_id,
        title=conversation.title,
        status=conversation.status,
        next_sequence_number=conversation.next_sequence_number,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        archived_at=conversation.archived_at,
    )


def to_message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sequence_number=message.sequence_number,
        client_message_id=message.client_message_id,
        sender_type=message.sender_type,
        content_type=message.content_type,
        content=message.content,
        status=message.status,
        metadata=message.metadata_,
        created_at=message.created_at,
    )


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: CreateConversationRequest,
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    conversation = await conversation_service.create_conversation(session, user_id, companion_id, body)
    return to_conversation_response(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ConversationResponse]:
    conversations = await conversation_service.list_conversations(session, user_id, companion_id)
    return [to_conversation_response(conversation) for conversation in conversations]


@router.post("/{conversation_id}/archive", response_model=ConversationResponse)
async def archive_conversation(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ConversationResponse:
    conversation = await conversation_service.archive_conversation(
        session,
        user_id,
        companion_id,
        conversation_id,
    )
    return to_conversation_response(conversation)


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def append_message(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: CreateMessageRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    result = await conversation_service.append_message(
        session,
        user_id,
        companion_id,
        conversation_id,
        body,
    )
    response.status_code = 201 if result.created else 200
    return to_message_response(result.message)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    messages = await conversation_service.list_messages(session, user_id, companion_id, conversation_id)
    return [to_message_response(message) for message in messages]
