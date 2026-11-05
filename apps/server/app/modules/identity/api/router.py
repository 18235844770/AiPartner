import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api.schemas import (
    CompanionResponse,
    CreateCompanionRequest,
    CreateUserRequest,
    UpdateCompanionRequest,
    UserResponse,
)
from app.modules.identity.services.identity_service import (
    IdentityService,
    to_companion_response,
    to_user_response,
)
from app.shared.database.session import get_session

router = APIRouter(prefix="/users", tags=["users"])
identity_service = IdentityService()


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await identity_service.create_user(session, body)
    return to_user_response(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await identity_service.get_user(session, user_id)
    return to_user_response(user)


@router.post("/{user_id}/companions", response_model=CompanionResponse, status_code=201)
async def create_companion(
    user_id: uuid.UUID,
    body: CreateCompanionRequest,
    session: AsyncSession = Depends(get_session),
) -> CompanionResponse:
    companion = await identity_service.create_companion(session, user_id, body)
    return to_companion_response(companion)


@router.get("/{user_id}/companions", response_model=list[CompanionResponse])
async def list_companions(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[CompanionResponse]:
    companions = await identity_service.list_companions(session, user_id)
    return [to_companion_response(companion) for companion in companions]


@router.patch("/{user_id}/companions/{companion_id}", response_model=CompanionResponse)
async def update_companion(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: UpdateCompanionRequest,
    session: AsyncSession = Depends(get_session),
) -> CompanionResponse:
    companion = await identity_service.update_companion(session, user_id, companion_id, body)
    return to_companion_response(companion)
