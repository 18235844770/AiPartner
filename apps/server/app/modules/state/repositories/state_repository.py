import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.enums import CompanionStatus
from app.modules.identity.repositories.models import Companion, User
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

    async def list_active_owners(
        self, session: AsyncSession, limit: int, *, managed_only: bool = False,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        statement = (
            select(Companion.id, Companion.owner_user_id)
            .join(CompanionState, CompanionState.companion_id == Companion.id)
            .join(User, User.id == Companion.owner_user_id)
            .where(Companion.status == CompanionStatus.ACTIVE.value)
            .where(User.status == "active")
            .order_by(CompanionState.updated_at.asc())
            .limit(limit)
        )
        if managed_only:
            statement = statement.where(Companion.initialization_status == "ready")
        return [(row[0], row[1]) for row in (await session.execute(statement)).all()]

    async def release_chat_references(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_ids: list[uuid.UUID],
        decision_ids: list[uuid.UUID],
    ) -> None:
        conditions = [StateEvent.conversation_id == conversation_id]
        if message_ids:
            conditions.append(StateEvent.message_id.in_(message_ids))
        if decision_ids:
            conditions.append(StateEvent.dialogue_decision_id.in_(decision_ids))
        await session.execute(
            update(StateEvent)
            .where(StateEvent.companion_id == companion_id, or_(*conditions))
            .values(message_id=None, dialogue_decision_id=None)
        )
