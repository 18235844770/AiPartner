import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dialogue.api.schemas import ProactiveTurnRequest, TurnResponse, UserTurnRequest
from app.modules.dialogue.services.dialogue_service import to_decision_response
from app.modules.dialogue.services.turn_service import DialogueTurnService
from app.shared.database.session import get_session

router = APIRouter(tags=["dialogue"])
turn_service = DialogueTurnService()


def get_turn_service() -> DialogueTurnService:
    return turn_service


@router.post(
    "/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/turns",
    response_model=TurnResponse,
    status_code=201,
)
async def respond_to_user(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: UserTurnRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    service: DialogueTurnService = Depends(get_turn_service),
) -> TurnResponse:
    result = await service.respond_to_user(
        session,
        user_id,
        companion_id,
        conversation_id,
        body.content,
        body.client_message_id,
    )
    if result.replay:
        response.status_code = 200
    return TurnResponse(
        user_message_id=result.user_message_id,
        companion_message_id=result.decision.result_message_id,
        decision=to_decision_response(result.decision),
    )


@router.post(
    "/users/{user_id}/companions/{companion_id}/proactive-turns",
    response_model=TurnResponse,
    status_code=201,
)
async def consider_proactive(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: ProactiveTurnRequest,
    session: AsyncSession = Depends(get_session),
    service: DialogueTurnService = Depends(get_turn_service),
) -> TurnResponse:
    result = await service.consider_proactive(session, user_id, companion_id, body.conversation_id)
    return TurnResponse(
        user_message_id=None,
        companion_message_id=result.decision.result_message_id,
        decision=to_decision_response(result.decision),
    )
