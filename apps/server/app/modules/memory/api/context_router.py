import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.memory.api.context_schemas import (
    AttentionTopicResponse,
    CreateAttentionTopicRequest,
    LinkAttentionMemoryRequest,
    SaveWorkingMemoryRequest,
    UpdateAttentionStatusRequest,
    WorkingMemoryResponse,
)
from app.modules.memory.services.context_service import MemoryContextService, to_working_response
from app.shared.database.session import get_session
from app.shared.exceptions.errors import NotFoundError

router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}",
    tags=["memory-context"],
)
context_service = MemoryContextService()


@router.get(
    "/conversations/{conversation_id}/working-memory",
    response_model=WorkingMemoryResponse,
)
async def get_working_memory(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> WorkingMemoryResponse:
    row = await context_service.get_working(session, user_id, companion_id, conversation_id)
    if row is None:
        raise NotFoundError("工作记忆不存在")
    return to_working_response(row)


@router.put(
    "/conversations/{conversation_id}/working-memory",
    response_model=WorkingMemoryResponse,
)
async def save_working_memory(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: SaveWorkingMemoryRequest,
    session: AsyncSession = Depends(get_session),
) -> WorkingMemoryResponse:
    row = await context_service.save_working(session, user_id, companion_id, conversation_id, body)
    return to_working_response(row)


@router.get("/attention-topics", response_model=list[AttentionTopicResponse])
async def list_attention_topics(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[AttentionTopicResponse]:
    return await context_service.list_attention_topics(session, user_id, companion_id)


@router.post("/attention-topics", response_model=AttentionTopicResponse, status_code=201)
async def create_attention_topic(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: CreateAttentionTopicRequest,
    session: AsyncSession = Depends(get_session),
) -> AttentionTopicResponse:
    return await context_service.create_attention_topic(session, user_id, companion_id, body)


@router.post("/attention-topics/{topic_id}/status", response_model=AttentionTopicResponse)
async def update_attention_status(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    topic_id: uuid.UUID,
    body: UpdateAttentionStatusRequest,
    session: AsyncSession = Depends(get_session),
) -> AttentionTopicResponse:
    return await context_service.set_attention_status(session, user_id, companion_id, topic_id, body.status)


@router.post("/attention-topics/{topic_id}/memories", response_model=AttentionTopicResponse)
async def link_attention_memory(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    topic_id: uuid.UUID,
    body: LinkAttentionMemoryRequest,
    session: AsyncSession = Depends(get_session),
) -> AttentionTopicResponse:
    return await context_service.link_memory(session, user_id, companion_id, topic_id, body.memory_id)
