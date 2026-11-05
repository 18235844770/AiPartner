import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.memory.api.schemas import (
    CreateMemoryRelationRequest,
    CreateMemoryRequest,
    CreateMemoryVersionRequest,
    MemoryEmbeddingResponse,
    MemoryRelationResponse,
    MemoryResponse,
    RecordEmbeddingRequest,
)
from app.modules.memory.services.memory_service import MemoryService, to_memory_response
from app.shared.database.session import get_session

router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}/memories",
    tags=["memories"],
)
memory_service = MemoryService()


@router.post("", response_model=MemoryResponse, status_code=201)
async def create_memory(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: CreateMemoryRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryResponse:
    memory, version, sources = await memory_service.create_memory(session, user_id, companion_id, body)
    return to_memory_response(memory, version, sources)


@router.get("", response_model=list[MemoryResponse])
async def list_memories(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[MemoryResponse]:
    rows = await memory_service.list_memories(session, user_id, companion_id)
    return [to_memory_response(memory, version, sources) for memory, version, sources in rows]


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> MemoryResponse:
    memory, version, sources = await memory_service.get_memory(session, user_id, companion_id, memory_id)
    return to_memory_response(memory, version, sources)


@router.post("/{memory_id}/versions", response_model=MemoryResponse, status_code=201)
async def add_memory_version(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    memory_id: uuid.UUID,
    body: CreateMemoryVersionRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryResponse:
    memory, version, sources = await memory_service.add_version(
        session,
        user_id,
        companion_id,
        memory_id,
        body,
    )
    return to_memory_response(memory, version, sources)


@router.post("/{memory_id}/relations", response_model=MemoryRelationResponse, status_code=201)
async def add_memory_relation(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    memory_id: uuid.UUID,
    body: CreateMemoryRelationRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryRelationResponse:
    relation = await memory_service.add_relation(session, user_id, companion_id, memory_id, body)
    return MemoryRelationResponse(
        id=relation.id,
        source_memory_id=relation.source_memory_id,
        target_memory_id=relation.target_memory_id,
    )


@router.post("/{memory_id}/embeddings", response_model=MemoryEmbeddingResponse, status_code=201)
async def record_memory_embedding(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    memory_id: uuid.UUID,
    body: RecordEmbeddingRequest,
    session: AsyncSession = Depends(get_session),
) -> MemoryEmbeddingResponse:
    embedding = await memory_service.record_embedding(session, user_id, companion_id, memory_id, body)
    return MemoryEmbeddingResponse(id=embedding.id, status=embedding.status)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    memory_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await memory_service.delete_memory(session, user_id, companion_id, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
