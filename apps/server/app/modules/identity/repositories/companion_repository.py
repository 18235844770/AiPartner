import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.enums import CompanionStatus
from app.modules.identity.repositories.models import Companion, User


class CompanionRepository:
    async def add(self, session: AsyncSession, companion: Companion) -> Companion:
        session.add(companion)
        await session.flush()
        return companion

    async def get(self, session: AsyncSession, companion_id: uuid.UUID) -> Companion | None:
        return await session.get(Companion, companion_id)

    async def get_managed(
        self, session: AsyncSession, owner_user_id: uuid.UUID, *, lock: bool = False,
    ) -> Companion | None:
        query = select(Companion).where(
            Companion.owner_user_id == owner_user_id,
            Companion.initialization_status.is_not(None),
        )
        return await session.scalar(query.with_for_update() if lock else query)

    async def due_for_review(self, session: AsyncSession, now: datetime, limit: int) -> list[Companion]:
        return list(await session.scalars(
            select(Companion).join(User, User.id == Companion.owner_user_id).where(
                User.status == "active", Companion.status == "active", Companion.initialization_status == "ready",
                or_(Companion.next_review_at.is_(None), Companion.next_review_at <= now),
            ).order_by(Companion.next_review_at.asc().nulls_first(), Companion.id).limit(limit)
            .with_for_update(of=Companion, skip_locked=True),
        ))

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
