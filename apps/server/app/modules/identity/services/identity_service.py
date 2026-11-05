import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api.schemas import (
    CompanionResponse,
    CreateCompanionRequest,
    CreateUserRequest,
    UpdateCompanionRequest,
    UserResponse,
)
from app.modules.identity.domain.enums import CompanionStatus, UserStatus
from app.modules.identity.repositories.companion_repository import CompanionRepository
from app.modules.identity.repositories.models import Companion, User
from app.modules.identity.repositories.user_repository import UserRepository
from app.shared.exceptions.errors import NotFoundError

logger = logging.getLogger(__name__)


class IdentityService:
    def __init__(
        self,
        users: UserRepository | None = None,
        companions: CompanionRepository | None = None,
    ) -> None:
        self._users = users or UserRepository()
        self._companions = companions or CompanionRepository()

    async def create_user(self, session: AsyncSession, data: CreateUserRequest) -> User:
        async with session.begin():
            user = await self._users.add(
                session,
                User(
                    display_name=data.display_name,
                    timezone=data.timezone,
                    locale=data.locale,
                    status=UserStatus.ACTIVE.value,
                ),
            )
        logger.info("created user %s", user.id)
        return user

    async def get_user(self, session: AsyncSession, user_id: uuid.UUID) -> User:
        async with session.begin():
            user = await self._users.get(session, user_id)
        if user is None:
            raise NotFoundError("用户不存在")
        return user

    async def get_owned_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> Companion:
        if session.in_transaction():
            return await self._scoped_companion(session, user_id, companion_id)
        async with session.begin():
            return await self._scoped_companion(session, user_id, companion_id)

    async def create_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        data: CreateCompanionRequest,
    ) -> Companion:
        async with session.begin():
            user = await self._users.get(session, user_id)
            if user is None:
                raise NotFoundError("用户不存在")
            if data.is_default:
                await self._companions.clear_active_default(session, user.id)
            companion = await self._companions.add(
                session,
                Companion(
                    owner_user_id=user.id,
                    name=data.name,
                    description=data.description,
                    status=CompanionStatus.ACTIVE.value,
                    is_default=data.is_default,
                ),
            )
        logger.info("created companion %s for user %s", companion.id, user.id)
        return companion

    async def list_companions(self, session: AsyncSession, user_id: uuid.UUID) -> list[Companion]:
        async with session.begin():
            user = await self._users.get(session, user_id)
            if user is None:
                raise NotFoundError("用户不存在")
            return await self._companions.list_for_user(session, user.id)

    async def update_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: UpdateCompanionRequest,
    ) -> Companion:
        async with session.begin():
            companion = await self._scoped_companion(session, user_id, companion_id)
            if data.name is not None:
                companion.name = data.name
            if data.description is not None:
                companion.description = data.description
            if data.status is not None:
                self._apply_status(companion, data.status)
            if data.is_default is True and companion.status == CompanionStatus.ACTIVE.value:
                await self._companions.clear_active_default(session, companion.owner_user_id)
                companion.is_default = True
            elif data.is_default is False:
                companion.is_default = False
            companion.updated_at = datetime.now(UTC)
            await session.flush()
        logger.info("updated companion %s", companion.id)
        return companion

    async def _scoped_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> Companion:
        user = await self._users.get(session, user_id)
        companion = await self._companions.get(session, companion_id)
        if user is None or companion is None or companion.owner_user_id != user.id:
            raise NotFoundError("Companion 不存在")
        return companion

    def _apply_status(self, companion: Companion, status: CompanionStatus) -> None:
        companion.status = status.value
        if status is CompanionStatus.ARCHIVED:
            companion.archived_at = datetime.now(UTC)
            return
        companion.archived_at = None


def to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        display_name=user.display_name,
        timezone=user.timezone,
        locale=user.locale,
        status=user.status,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def to_companion_response(companion: Companion) -> CompanionResponse:
    return CompanionResponse(
        id=companion.id,
        owner_user_id=companion.owner_user_id,
        name=companion.name,
        description=companion.description,
        status=companion.status,
        is_default=companion.is_default,
        created_at=companion.created_at,
        updated_at=companion.updated_at,
        archived_at=companion.archived_at,
    )
