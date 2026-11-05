import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.persona.api.schemas import CreatePersonaVersionRequest, InitializePersonaRequest, PersonaResponse
from app.modules.persona.services.persona_service import PersonaService, to_persona_response
from app.shared.database.session import get_session

router = APIRouter(
    prefix="/users/{user_id}/companions/{companion_id}/persona",
    tags=["persona"],
)
persona_service = PersonaService()


@router.post("", response_model=PersonaResponse, status_code=201)
async def initialize_persona(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: InitializePersonaRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonaResponse:
    profile, version = await persona_service.initialize(session, user_id, companion_id, body)
    return to_persona_response(profile, version)


@router.get("", response_model=PersonaResponse)
async def get_persona(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PersonaResponse:
    profile, version = await persona_service.get_current(session, user_id, companion_id)
    return to_persona_response(profile, version)


@router.post("/versions", response_model=PersonaResponse, status_code=201)
async def add_persona_version(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: CreatePersonaVersionRequest,
    session: AsyncSession = Depends(get_session),
) -> PersonaResponse:
    profile, version = await persona_service.add_version(session, user_id, companion_id, body)
    return to_persona_response(profile, version)
