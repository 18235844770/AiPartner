import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.state.api.schemas import ApplyStateChangeRequest, InitializeStateRequest, StateEventResponse, StateResponse
from app.modules.state.services.state_service import StateService, to_event_response, to_state_response
from app.shared.database.session import get_session

router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}/state",
    tags=["state"],
)
state_service = StateService()


@router.post("", response_model=StateResponse, status_code=201)
async def initialize_state(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: InitializeStateRequest,
    session: AsyncSession = Depends(get_session),
) -> StateResponse:
    del body
    state = await state_service.initialize(session, user_id, companion_id)
    return to_state_response(state)


@router.get("", response_model=StateResponse)
async def get_state(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> StateResponse:
    state = await state_service.get_current(session, user_id, companion_id)
    return to_state_response(state)


@router.get("/events", response_model=list[StateEventResponse])
async def list_state_events(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[StateEventResponse]:
    events = await state_service.list_events(session, user_id, companion_id)
    return [to_event_response(event) for event in events]


@router.post("/changes", response_model=StateResponse)
async def apply_state_change(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: ApplyStateChangeRequest,
    session: AsyncSession = Depends(get_session),
) -> StateResponse:
    state = await state_service.apply_change(session, user_id, companion_id, body)
    return to_state_response(state)
