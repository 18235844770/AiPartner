import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.enums import CompanionStatus
from app.modules.identity.repositories.models import Companion
from app.modules.state.repositories.models import CompanionState, StateEvent


class StateRepository:
    async def add_state(self, session: AsyncSession, state: CompanionState) -> CompanionState:
        session.add(state)
        await session.flush()
        return state

    async def add_event(self, session: AsyncSession, event: StateEvent) -> StateEvent:
        session.add(event)
        await session.flush()
        return event

    async def get_for_companion(self, session: AsyncSession, companion_id: uuid.UUID) -> CompanionState | None:
        statement = select(CompanionState).where(CompanionState.companion_id == companion_id)
        return (await session.execute(statement)).scalar_one_or_none()

    async def get_for_update(self, session: AsyncSession, companion_id: uuid.UUID) -> CompanionState | None:
        statement = (
            select(CompanionState)
            .where(CompanionState.companion_id == companion_id)
            .with_for_update()
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def list_events(self, session: AsyncSession, companion_id: uuid.UUID) -> list[StateEvent]:
        statement = (
            select(StateEvent)
            .where(StateEvent.companion_id == companion_id)
            .order_by(StateEvent.version_after.asc().nulls_last(), StateEvent.created_at.asc())
        )
        return list((await session.execute(statement)).scalars().all())

    async def list_active_owners(self, session: AsyncSession, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
        statement = (
            select(Companion.id, Companion.owner_user_id)
            .join(CompanionState, CompanionState.companion_id == Companion.id)
            .where(Companion.status == CompanionStatus.ACTIVE.value)
            .order_by(CompanionState.updated_at.asc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in (await session.execute(statement)).all()]
