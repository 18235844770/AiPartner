import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.enums import CompanionStatus
from app.modules.identity.repositories.models import Companion


class CompanionRepository:
    async def add(self, session: AsyncSession, companion: Companion) -> Companion:
        session.add(companion)
        await session.flush()
        return companion

    async def get(self, session: AsyncSession, companion_id: uuid.UUID) -> Companion | None:
        return await session.get(Companion, companion_id)

    async def list_for_user(self, session: AsyncSession, owner_user_id: uuid.UUID) -> list[Companion]:
        result = await session.scalars(
            select(Companion)
            .where(Companion.owner_user_id == owner_user_id)
            .order_by(Companion.created_at)
        )
        return list(result.all())

    async def clear_active_default(self, session: AsyncSession, owner_user_id: uuid.UUID) -> None:
        await session.execute(
            update(Companion)
            .where(
                Companion.owner_user_id == owner_user_id,
                Companion.is_default.is_(True),
                Companion.status == CompanionStatus.ACTIVE.value,
            )
            .values(is_default=False)
        )
