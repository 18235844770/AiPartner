"""按周期评估要不要主动联系。检查本身不绕过交流决策。"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.conversation.domain.enums import ConversationStatus, MessageStatus, SenderType
from app.modules.conversation.repositories.models import Conversation
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.api.stream_schemas import TurnCompleted, TurnFailed
from app.modules.dialogue.domain.proactive import ProactiveMessage, frequency_block
from app.modules.dialogue.services.turn_service import DialogueTurnService
from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.state.domain.enums import InteractionMode
from app.modules.state.domain.snapshots import InteractionState
from app.modules.state.repositories.state_repository import StateRepository
from app.modules.state.services.state_service import StateService
from app.shared.database.session import get_session_factory

logger = logging.getLogger(__name__)

_SCHEDULE_LIMIT = 50
_PROACTIVE_MODES = {InteractionMode.AVAILABLE.value, InteractionMode.WAITING.value}
_VISIBLE = {MessageStatus.RECORDED.value, MessageStatus.COMPLETED.value}
_SPEAKERS = {SenderType.USER.value, SenderType.COMPANION.value}


class ProactiveCheckService:
    def __init__(
        self,
        turns: DialogueTurnService | None = None,
        states: StateService | None = None,
        repository: StateRepository | None = None,
        conversations: ConversationService | None = None,
        identity: IdentityService | None = None,
        tasks: BackgroundTaskService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._turns = turns or DialogueTurnService()
        self._states = states or StateService()
        self._repository = repository or StateRepository()
        self._conversations = conversations or ConversationService()
        self._identity = identity or IdentityService()
        self._tasks = tasks or BackgroundTaskService()
        self._session_factory = session_factory or get_session_factory()

    async def check(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        now: datetime | None = None,
    ) -> dict[str, object]:
        if session.in_transaction():
            return await self._check(session, user_id=user_id, companion_id=companion_id, now=now or datetime.now(UTC))
        async with session.begin():
            return await self._check(session, user_id=user_id, companion_id=companion_id, now=now or datetime.now(UTC))

    async def schedule_due(self, *, now: datetime | None = None, limit: int = _SCHEDULE_LIMIT) -> int:
        moment = now or datetime.now(UTC)
        bucket = moment.strftime("%Y%m%d%H")
        async with self._session_factory() as session:
            async with session.begin():
                targets = await self._states.list_active_owners(session, limit)
                created = 0
                for companion_id, user_id in targets:
                    result = await self._tasks.create(
                        session,
                        CreateBackgroundTaskRequest(
                            user_id=user_id,
                            companion_id=companion_id,
                            task_type=BackgroundTaskType.PROACTIVE_CHECK,
                            task_key=f"proactive-check:{companion_id}:{bucket}",
                            queue_name="dialogue",
                            payload={"user_id": str(user_id)},
                            max_retries=2,
                            scheduled_at=moment,
                        ),
                    )
                    if result.created:
                        created += 1
        if created:
            logger.info("scheduled %s proactive checks", created)
        return created

    async def _check(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        now: datetime,
    ) -> dict[str, object]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        current = await self._repository.get_for_companion(session, companion_id)
        if current is None:
            return {"checked": False, "sent": False, "reason": "missing"}
        interaction = InteractionState.model_validate(current.interaction)
        if not interaction.proactive_allowed or interaction.mode.value not in _PROACTIVE_MODES:
            return {"checked": True, "sent": False, "reason": "proactive_not_allowed"}
        quiet_until = interaction.quiet_until
        if quiet_until is not None and quiet_until > now:
            return {"checked": True, "sent": False, "reason": "quiet_until"}
        conversations = await self._conversations.list_conversations(session, user_id, companion_id)
        conversation = _latest_active(conversations)
        if conversation is None:
            return {"checked": True, "sent": False, "reason": "no_conversation"}
        messages = await self._conversations.list_messages(session, user_id, companion_id, conversation.id)
        visible = [
            ProactiveMessage(sender_type=item.sender_type, created_at=item.created_at)
            for item in messages
            if item.status in _VISIBLE and item.sender_type in _SPEAKERS
        ]
        blocked = frequency_block(visible, now)
        if blocked is not None:
            return {"checked": True, "sent": False, "reason": blocked}
        outcome = "quiet"
        sent = False
        async for event in self._turns.iter_proactive_turn(session, user_id, companion_id, conversation.id):
            if isinstance(event, TurnCompleted):
                outcome = event.outcome
                sent = event.outcome == "replied"
            elif isinstance(event, TurnFailed):
                outcome = "failed"
                sent = False
        logger.info("proactive check for companion %s outcome %s", companion_id, outcome)
        return {"checked": True, "sent": sent, "outcome": outcome}


def _latest_active(conversations: list[Conversation]) -> Conversation | None:
    active = [item for item in conversations if item.status == ConversationStatus.ACTIVE.value]
    if not active:
        return None
    return max(active, key=lambda item: item.last_message_at or item.created_at)
