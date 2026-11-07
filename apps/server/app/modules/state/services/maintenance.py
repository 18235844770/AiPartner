"""按时间维护内部状态。没有变化时不写新版本。"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from pydantic import ValidationError

from app.modules.persona.domain.archive import (
    PersonaArchive,
    RelationshipSelfAssertion,
    forgiveness_half_life_multipliers,
)
from app.modules.persona.services.persona_service import PersonaService
from app.modules.state.api.schemas import ApplyStateChangeRequest
from app.modules.state.domain.enums import StateSourceType
from app.modules.state.domain.maintenance import AbsenceDispositionFactors, factors_from_disposition, plan_maintenance
from app.modules.state.domain.snapshots import EmotionState, InteractionState, RelationshipState
from app.modules.state.repositories.state_repository import StateRepository
from app.modules.state.services.state_service import StateService
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import AppError

logger = logging.getLogger(__name__)

_SCHEDULE_LIMIT = 50


class StateMaintenanceService:
    def __init__(
        self,
        states: StateService | None = None,
        repository: StateRepository | None = None,
        identity: IdentityService | None = None,
        tasks: BackgroundTaskService | None = None,
        personas: PersonaService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._states = states or StateService()
        self._repository = repository or StateRepository()
        self._identity = identity or IdentityService()
        self._tasks = tasks or BackgroundTaskService()
        self._personas = personas or PersonaService()
        self._session_factory = session_factory or get_session_factory()

    async def maintain(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        if session.in_transaction():
            return await self._maintain(
                session,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                message_id=message_id,
                now=now or datetime.now(UTC),
            )
        async with session.begin():
            return await self._maintain(
                session,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                message_id=message_id,
                now=now or datetime.now(UTC),
            )

    async def schedule_due(self, *, now: datetime | None = None, limit: int = _SCHEDULE_LIMIT) -> int:
        moment = now or datetime.now(UTC)
        bucket = moment.strftime("%Y%m%d%H")
        async with self._session_factory() as session:
            async with session.begin():
                targets = await self._repository.list_active_owners(session, limit)
                created = 0
                for companion_id, user_id in targets:
                    result = await self._tasks.create(
                        session,
                        CreateBackgroundTaskRequest(
                            user_id=user_id,
                            companion_id=companion_id,
                            task_type=BackgroundTaskType.STATE_MAINTENANCE,
                            task_key=f"state-maintenance:{companion_id}:{bucket}",
                            queue_name="state",
                            payload={"user_id": str(user_id)},
                            max_retries=2,
                            scheduled_at=moment,
                        ),
                    )
                    if result.created:
                        created += 1
        if created:
            logger.info("scheduled %s state maintenance tasks", created)
        return created

    async def _maintain(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
        now: datetime,
    ) -> dict[str, object]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        current = await self._repository.get_for_companion(session, companion_id)
        if current is None:
            return {"changed": False, "reason": "missing"}
        relationship = RelationshipState.model_validate(current.relationship)
        plan = plan_maintenance(
            EmotionState.model_validate(current.emotion),
            InteractionState.model_validate(current.interaction),
            now,
            relationship=relationship,
            absence_factors=await self._absence_factors(session, user_id, companion_id),
            half_life_multipliers=await self._forgiveness_multipliers(session, user_id, companion_id),
        )
        if plan.reason is None:
            return {"changed": False, "reason": "unchanged"}
        saved = await self._states.apply_change(
            session,
            user_id,
            companion_id,
            ApplyStateChangeRequest(
                expected_version=current.version,
                source_type=StateSourceType.BACKGROUND_TASK,
                reason=plan.reason,
                conversation_id=conversation_id,
                message_id=message_id,
                emotion=plan.emotion,
                relationship=plan.relationship,
                interaction=plan.interaction,
            ),
        )
        logger.info("maintained state %s to version %s", saved.id, saved.version)
        return {"changed": True, "version": saved.version}

    async def _absence_factors(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> AbsenceDispositionFactors:
        try:
            _profile, version = await self._personas.get_current(session, user_id, companion_id)
        except AppError:
            return AbsenceDispositionFactors()
        archive = version.archive if isinstance(version.archive, dict) else None
        if not archive:
            return AbsenceDispositionFactors()
        relationship = archive.get("relationship")
        if not isinstance(relationship, dict):
            return AbsenceDispositionFactors()
        disposition = relationship.get("attachment_disposition")
        if not isinstance(disposition, dict):
            return AbsenceDispositionFactors()
        return factors_from_disposition(disposition)

    async def _forgiveness_multipliers(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> dict[str, float] | None:
        try:
            _profile, version = await self._personas.get_current(session, user_id, companion_id)
        except AppError:
            return None
        archive = version.archive if isinstance(version.archive, dict) else None
        if not archive:
            return None
        try:
            assertion = PersonaArchive.model_validate(archive).relationship.self_assertion
        except ValidationError:
            raw = archive.get("relationship")
            if not isinstance(raw, dict):
                return None
            payload = raw.get("self_assertion")
            if not isinstance(payload, dict):
                return None
            try:
                assertion = RelationshipSelfAssertion.model_validate(payload)
            except ValidationError:
                return None
        return forgiveness_half_life_multipliers(assertion.forgiveness_tendency)
