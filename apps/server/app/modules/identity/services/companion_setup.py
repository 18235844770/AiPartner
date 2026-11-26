import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import CreateConversationRequest
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.identity.repositories.auth_repository import AuthRepository
from app.modules.identity.repositories.companion_repository import CompanionRepository
from app.modules.identity.repositories.models import Companion
from app.modules.persona.api.schemas import InitializePersonaRequest
from app.modules.persona.services.persona_service import PersonaService
from app.modules.state.services.state_service import StateService
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import ConflictError, NotFoundError


logger = logging.getLogger(__name__)


class CompanionSetupService:
    def __init__(self) -> None:
        self._accounts = AuthRepository()
        self._companions = CompanionRepository()
        self._personas = PersonaService()
        self._states = StateService()
        self._conversations = ConversationService()

    async def get(self, session: AsyncSession, user_id: uuid.UUID) -> Companion:
        if session.in_transaction():
            return await self._require_companion(session, user_id)
        async with session.begin():
            return await self._require_companion(session, user_id)

    async def get_ready(self, session: AsyncSession, user_id: uuid.UUID) -> Companion:
        companion = await self.get(session, user_id)
        if companion.initialization_status != "ready":
            raise ConflictError("伴侣仍在初始化")
        return companion

    async def claim_reviews(
        self, session: AsyncSession, now: datetime, limit: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        due = await self._companions.due_for_review(session, now, limit)
        for companion in due:
            companion.next_review_at = now + timedelta(minutes=5)
        return [(companion.id, companion.owner_user_id) for companion in due]

    async def initialize(self, user_id: uuid.UUID) -> None:
        async with get_session_factory()() as session:
            try:
                async with session.begin():
                    if await self._accounts.get_active_user(session, user_id, lock=True) is None:
                        return
                    companion = await self._require_companion(session, user_id, lock=True)
                    if companion.initialization_status == "ready":
                        return
                    await self._personas.initialize(session, user_id, companion.id, InitializePersonaRequest())
                    await self._states.initialize(session, user_id, companion.id)
                    thread = await self._conversations.create_conversation(
                        session, user_id, companion.id, CreateConversationRequest(),
                    )
                    thread.conversation.is_managed = True
                    companion.initialization_status = "ready"
                    companion.initialized_at = datetime.now(UTC)
            except Exception as exc:
                logger.error("companion initialization failed for user %s (%s)", user_id, type(exc).__name__)
                async with session.begin():
                    companion = await self._companions.get_managed(session, user_id, lock=True)
                    if companion is not None and companion.initialization_status != "ready":
                        companion.initialization_status = "failed"

    async def _require_companion(
        self, session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False,
    ) -> Companion:
        companion = await self._companions.get_managed(session, user_id, lock=lock)
        if companion is None:
            raise NotFoundError("伴侣不存在")
        return companion
