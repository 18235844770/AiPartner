import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dialogue.api.schemas import ProactiveTurnRequest, UserTurnRequest
from app.modules.dialogue.api.stream_schemas import TurnStreamEvent, encode_sse
from app.modules.dialogue.services.turn_service import DialogueTurnService
from app.shared.database.session import get_session

router = APIRouter(tags=["dialogue"])
turn_service = DialogueTurnService()


def get_turn_service() -> DialogueTurnService:
    return turn_service


@router.post(
    "/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/turns",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def respond_to_user(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: UserTurnRequest,
    session: AsyncSession = Depends(get_session),
    service: DialogueTurnService = Depends(get_turn_service),
) -> StreamingResponse:
    stream = service.iter_user_turn(
        session,
        user_id,
        companion_id,
        conversation_id,
        body.content,
        body.client_message_id,
    )
    return await _event_response(stream)


@router.post(
    "/users/{user_id}/companions/{companion_id}/proactive-turns",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def consider_proactive(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: ProactiveTurnRequest,
    session: AsyncSession = Depends(get_session),
    service: DialogueTurnService = Depends(get_turn_service),
) -> StreamingResponse:
    stream = service.iter_proactive_turn(session, user_id, companion_id, body.conversation_id)
    return await _event_response(stream)


async def _event_response(stream: AsyncIterator[TurnStreamEvent]) -> StreamingResponse:
    first = await anext(stream)

    async def frames() -> AsyncIterator[str]:
        yield encode_sse(first)
        async for event in stream:
            yield encode_sse(event)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
