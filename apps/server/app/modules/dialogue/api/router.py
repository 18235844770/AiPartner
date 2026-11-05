import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dialogue.api.schemas import DecisionResponse, RealizeDecisionRequest, RecordDecisionRequest
from app.modules.dialogue.services.dialogue_service import DialogueService, to_decision_response
from app.shared.database.session import get_session

router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}/decisions",
    tags=["dialogue"],
)
dialogue_service = DialogueService()


@router.post("", response_model=DecisionResponse, status_code=201)
async def record_decision(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: RecordDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    decision = await dialogue_service.record(session, user_id, companion_id, body)
    return to_decision_response(decision)


@router.get("", response_model=list[DecisionResponse])
async def list_decisions(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[DecisionResponse]:
    decisions = await dialogue_service.list_decisions(session, user_id, companion_id)
    return [to_decision_response(decision) for decision in decisions]


@router.get("/{decision_id}", response_model=DecisionResponse)
async def get_decision(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    decision_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    decision = await dialogue_service.get_decision(session, user_id, companion_id, decision_id)
    return to_decision_response(decision)


@router.post("/{decision_id}/realization", response_model=DecisionResponse)
async def realize_decision(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    decision_id: uuid.UUID,
    body: RealizeDecisionRequest,
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    decision = await dialogue_service.realize(session, user_id, companion_id, decision_id, body)
    return to_decision_response(decision)
