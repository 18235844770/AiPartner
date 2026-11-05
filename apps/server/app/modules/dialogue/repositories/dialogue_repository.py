import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dialogue.repositories.models import DialogueDecision


class DialogueRepository:
    async def add(self, session: AsyncSession, decision: DialogueDecision) -> DialogueDecision:
        session.add(decision)
        await session.flush()
        return decision

    async def get_for_companion(
        self,
        session: AsyncSession,
        decision_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> DialogueDecision | None:
        statement = select(DialogueDecision).where(
            DialogueDecision.id == decision_id,
            DialogueDecision.companion_id == companion_id,
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def find_by_trigger_message(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> DialogueDecision | None:
        statement = (
            select(DialogueDecision)
            .where(
                DialogueDecision.companion_id == companion_id,
                DialogueDecision.trigger_message_id == message_id,
            )
            .order_by(DialogueDecision.created_at.asc())
            .limit(1)
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def get_for_update(
        self,
        session: AsyncSession,
        decision_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> DialogueDecision | None:
        statement = (
            select(DialogueDecision)
            .where(
                DialogueDecision.id == decision_id,
                DialogueDecision.companion_id == companion_id,
            )
            .with_for_update()
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def list_for_companion(self, session: AsyncSession, companion_id: uuid.UUID) -> list[DialogueDecision]:
        statement = (
            select(DialogueDecision)
            .where(DialogueDecision.companion_id == companion_id)
            .order_by(DialogueDecision.created_at.desc())
        )
        return list((await session.execute(statement)).scalars().all())
