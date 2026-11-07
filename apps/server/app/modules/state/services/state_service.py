import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.identity.services.identity_service import IdentityService
from app.modules.state.api.schemas import ApplyStateChangeRequest, StateEventResponse, StateResponse
from app.modules.state.domain.enums import StateEventType, StateSourceType, event_type_for
from app.modules.state.domain.snapshots import (
    EmotionState,
    InteractionState,
    MotivationState,
    RelationshipState,
    dump_snapshot,
    initial_snapshots,
)
from app.modules.state.repositories.models import CompanionState, StateEvent
from app.modules.state.repositories.state_repository import StateRepository
from app.shared.exceptions.errors import AppError, ConflictError, NotFoundError

logger = logging.getLogger(__name__)

INITIAL_REASON = "初始状态"
_DIMENSIONS = ("emotion", "relationship", "interaction", "motivation")


class StateService:
    def __init__(
        self,
        states: StateRepository | None = None,
        identity: IdentityService | None = None,
        conversations: ConversationService | None = None,
    ) -> None:
        self._states = states or StateRepository()
        self._identity = identity or IdentityService()
        self._conversations = conversations or ConversationService()

    async def initialize(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> CompanionState:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            existing = await self._states.get_for_companion(session, companion_id)
            if existing is not None:
                raise ConflictError("状态已经初始化")
            now = datetime.now(UTC)
            snapshots = initial_snapshots(now)
            dumped = {name: dump_snapshot(model) for name, model in snapshots.items()}
            state = CompanionState(
                companion_id=companion_id,
                emotion=dumped["emotion"],
                relationship=dumped["relationship"],
                interaction=dumped["interaction"],
                motivation=dumped["motivation"],
                updated_at=now,
                version=1,
            )
            await self._states.add_state(session, state)
            await self._states.add_event(
                session,
                StateEvent(
                    companion_id=companion_id,
                    event_type=StateEventType.STATE_INITIALIZED.value,
                    source_type=StateSourceType.SYSTEM.value,
                    version_before=None,
                    version_after=1,
                    changes={name: {"before": None, "after": dumped[name]} for name in _DIMENSIONS},
                    reason=INITIAL_REASON,
                    created_at=now,
                ),
            )
        logger.info("initialized state %s for companion %s", state.id, companion_id)
        return state

    async def get_current(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> CompanionState:
        if session.in_transaction():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require(session, companion_id)
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require(session, companion_id)

    async def list_active_owners(
        self,
        session: AsyncSession,
        limit: int,
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        if session.in_transaction():
            return await self._states.list_active_owners(session, limit)
        async with session.begin():
            return await self._states.list_active_owners(session, limit)

    async def list_events(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[StateEvent]:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            await self._require(session, companion_id)
            return await self._states.list_events(session, companion_id)

    async def apply_change(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: ApplyStateChangeRequest,
    ) -> CompanionState:
        if session.in_transaction():
            state = await self._apply_change(session, user_id, companion_id, data)
        else:
            async with session.begin():
                state = await self._apply_change(session, user_id, companion_id, data)
        logger.info("updated state %s to version %s", state.id, state.version)
        return state

    async def _apply_change(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: ApplyStateChangeRequest,
    ) -> CompanionState:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        state = await self._states.get_for_update(session, companion_id)
        if state is None:
            raise NotFoundError("状态不存在")
        if state.version != data.expected_version:
            raise ConflictError("状态版本不匹配")
        conversation_id, message_id = await self._linked_sources(session, user_id, companion_id, data)
        now = datetime.now(UTC)
        changes = self._collect_changes(state, data, now)
        if not changes:
            raise AppError("状态没有变化")
        version_before = state.version
        state.version = version_before + 1
        state.updated_at = now
        await self._states.add_event(
            session,
            StateEvent(
                companion_id=companion_id,
                event_type=event_type_for(list(changes)).value,
                source_type=data.source_type.value,
                conversation_id=conversation_id,
                message_id=message_id,
                dialogue_decision_id=data.dialogue_decision_id,
                version_before=version_before,
                version_after=state.version,
                changes=changes,
                reason=data.reason,
                created_at=now,
            ),
        )
        return state

    async def _require(self, session: AsyncSession, companion_id: uuid.UUID) -> CompanionState:
        state = await self._states.get_for_companion(session, companion_id)
        if state is None:
            raise NotFoundError("状态不存在")
        return state

    async def _linked_sources(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: ApplyStateChangeRequest,
    ) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        message = None
        if data.message_id is not None:
            message = await self._conversations.get_owned_message(session, user_id, companion_id, data.message_id)
        conversation_id = data.conversation_id
        if conversation_id is not None:
            conversation = await self._conversations.get_owned_conversation(
                session,
                user_id,
                companion_id,
                conversation_id,
            )
            if message is not None and message.conversation_id != conversation.id:
                raise AppError("消息不属于该会话")
        elif message is not None:
            conversation_id = message.conversation_id
        return conversation_id, data.message_id

    def _collect_changes(
        self,
        state: CompanionState,
        data: ApplyStateChangeRequest,
        now: datetime,
    ) -> dict[str, object]:
        changes: dict[str, object] = {}
        incoming = {
            "emotion": data.emotion,
            "relationship": data.relationship,
            "interaction": data.interaction,
            "motivation": data.motivation,
        }
        for name in _DIMENSIONS:
            model = incoming[name]
            if model is None:
                continue
            current = getattr(state, name)
            if name == "emotion":
                assert data.emotion is not None
                before = dump_snapshot(EmotionState.model_validate(current))
                before_body = {key: value for key, value in before.items() if key != "updated_at"}
                after_body = data.emotion.model_dump(mode="json")
                if before_body == after_body:
                    continue
                after_model = EmotionState(updated_at=now, **data.emotion.model_dump())
                after = dump_snapshot(after_model)
            else:
                before = dump_snapshot(type(model).model_validate(current))
                after = dump_snapshot(model)
                if before == after:
                    continue
            setattr(state, name, after)
            changes[name] = {"before": before, "after": after}
        return changes


def to_state_response(state: CompanionState) -> StateResponse:
    return StateResponse(
        id=state.id,
        companion_id=state.companion_id,
        version=state.version,
        updated_at=state.updated_at,
        emotion=EmotionState.model_validate(state.emotion),
        relationship=RelationshipState.model_validate(state.relationship),
        interaction=InteractionState.model_validate(state.interaction),
        motivation=MotivationState.model_validate(state.motivation),
    )


def to_event_response(event: StateEvent) -> StateEventResponse:
    return StateEventResponse(
        id=event.id,
        companion_id=event.companion_id,
        event_type=StateEventType(event.event_type),
        source_type=StateSourceType(event.source_type),
        conversation_id=event.conversation_id,
        message_id=event.message_id,
        dialogue_decision_id=event.dialogue_decision_id,
        version_before=event.version_before,
        version_after=event.version_after,
        changes=event.changes,
        reason=event.reason,
        created_at=event.created_at,
    )
