import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import CreateMessageRequest
from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.api.stream_schemas import (
    MessageCompleted,
    MessageDelta,
    MessageStarted,
    TurnCompleted,
    TurnErrorBody,
    TurnFailed,
    TurnStarted,
    TurnStreamEvent,
    failure_for,
)
from app.modules.dialogue.domain.context import decision_messages, final_send, realization_messages
from app.modules.dialogue.domain.enums import DecisionStatus, DialogueAction, TriggerType
from app.modules.dialogue.domain.suggestion import (
    FALLBACK_USER_TEXT,
    ModelDecisionSuggestion,
    blocked_proactive,
    proactive_fallback,
    user_fallback,
)
from app.modules.dialogue.domain.turn_state import plan_turn_state
from app.modules.dialogue.repositories.models import DialogueDecision
from app.modules.dialogue.services.dialogue_service import DialogueService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType, ModelConfigKey
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.model_call_log_service import ModelCallLogService
from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelOutputError
from app.modules.memory.services.context_service import MemoryContextService
from app.modules.memory.services.retrieval import MemoryRetrievalService
from app.modules.model_adapter.domain.messages import ChatMessage, TextCompletion
from app.modules.model_adapter.services.model_adapter import ModelCallScope
from app.modules.persona.services.persona_service import PersonaService
from app.modules.state.api.schemas import ApplyStateChangeRequest
from app.modules.state.domain.enums import InteractionMode, StateSourceType
from app.modules.state.domain.snapshots import EmotionState, InteractionState, MotivationState, RelationshipState
from app.modules.state.services.state_service import StateService
from app.shared.exceptions.errors import AppError

logger = logging.getLogger(__name__)


class DecisionModel(Protocol):
    async def complete_structured(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        result_type: type[ModelDecisionSuggestion],
        scope: ModelCallScope,
    ) -> ModelDecisionSuggestion: ...

    async def complete_text(
        self,
        task: ModelConfigKey,
        messages: list[ChatMessage],
        scope: ModelCallScope,
        *,
        json_object: bool = False,
    ) -> TextCompletion: ...


@dataclass(frozen=True)
class TurnContext:
    mbti_type: str
    core_traits: dict[str, object]
    communication_preferences: dict[str, object]
    emotion_primary: str
    emotion_cause: str
    relationship_summary: str
    interaction_mode: str
    proactive_allowed: bool
    recent_messages: list[dict[str, str]]
    memories: list[dict[str, object]]
    immediate_facts: list[dict[str, str]]
    working_memory: dict[str, object] | None = None
    attention_topics: list[dict[str, object]] | None = None
    archive: dict[str, object] | None = None
    versions: dict[str, str] | None = None

    def decision_input(self, repair: bool) -> list[ChatMessage]:
        return decision_messages(
            mbti_type=self.mbti_type,
            core_traits=self.core_traits,
            communication_preferences=self.communication_preferences,
            emotion_primary=self.emotion_primary,
            emotion_cause=self.emotion_cause,
            relationship_summary=self.relationship_summary,
            interaction_mode=self.interaction_mode,
            proactive_allowed=self.proactive_allowed,
            recent_messages=self.recent_messages,
            repair=repair,
            memories=self.memories,
            immediate_facts=self.immediate_facts,
            working_memory=self.working_memory,
            attention_topics=self.attention_topics,
            archive=self.archive,
            versions=self.versions,
        )

    def realization_input(self, suggestion: ModelDecisionSuggestion) -> list[ChatMessage]:
        return realization_messages(
            suggestion,
            self.recent_messages,
            self.memories,
            self.immediate_facts,
            mbti_type=self.mbti_type,
            core_traits=self.core_traits,
            communication_preferences=self.communication_preferences,
            emotion_primary=self.emotion_primary,
            emotion_cause=self.emotion_cause,
            relationship_summary=self.relationship_summary,
            interaction_mode=self.interaction_mode,
            proactive_allowed=self.proactive_allowed,
            working_memory=self.working_memory,
            archive=self.archive,
            versions=self.versions,
        )


class DialogueTurnService:
    def __init__(
        self,
        dialogue: DialogueService | None = None,
        conversations: ConversationService | None = None,
        personas: PersonaService | None = None,
        states: StateService | None = None,
        adapter: DecisionModel | None = None,
        tasks: BackgroundTaskService | None = None,
        retrieval: MemoryRetrievalService | None = None,
        contexts: MemoryContextService | None = None,
        logs: ModelCallLogService | None = None,
    ) -> None:
        self._dialogue = dialogue or DialogueService()
        self._conversations = conversations or ConversationService()
        self._personas = personas or PersonaService()
        self._states = states or StateService()
        self._adapter = adapter if adapter is not None else _default_adapter()
        self._tasks = tasks or BackgroundTaskService()
        self._retrieval = retrieval or MemoryRetrievalService()
        self._contexts = contexts or MemoryContextService()
        self._logs = logs or ModelCallLogService()

    async def iter_user_turn(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        client_message_id: uuid.UUID | None = None,
    ) -> AsyncIterator[TurnStreamEvent]:
        turn_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        sequence = _Sequence()
        parts: list[str] = []
        message_id: uuid.UUID | None = None
        decision_id: uuid.UUID | None = None
        settled = False

        async def abandon(status: DecisionStatus) -> None:
            nonlocal settled
            if settled or decision_id is None:
                return
            await self._dialogue.close_unfinished(
                session,
                user_id,
                companion_id,
                decision_id,
                final_status=status,
                message_id=message_id,
                content="".join(parts),
            )
            settled = True

        try:
            async with session.begin():
                appended = await self._conversations.append_message(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    CreateMessageRequest(
                        sender_type=SenderType.USER,
                        content=content,
                        client_message_id=client_message_id,
                    ),
                )
                await self._schedule_memory_extract(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    appended.message.id,
                )
            if not appended.created:
                existing = await self._dialogue.find_by_trigger_message(
                    session,
                    user_id,
                    companion_id,
                    appended.message.id,
                )
                if existing is not None:
                    settled = True
                    async for event in self._replay_turn(session, user_id, companion_id, conversation_id, existing):
                        yield event
                    return
            yield TurnStarted(turn_id=turn_id, conversation_id=conversation_id, sequence=sequence.next())
            context = await self._context(session, user_id, companion_id, conversation_id, content)
            scope = ModelCallScope(
                trace_id=trace_id,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                context_versions=context.versions or {},
            )
            suggestion, validation = await self._choose(context, scope, user_fallback)
            action, should_send = final_send(suggestion)
            decision = await self._save(
                session,
                user_id,
                companion_id,
                TriggerType.USER_MESSAGE,
                conversation_id,
                appended.message.id,
                suggestion,
                action,
                should_send,
                validation,
                decision_id=turn_id,
            )
            decision_id = decision.id
            await self._link_calls(trace_id, decision.id)
            await self._contexts.record_topic_transition(
                session,
                user_id,
                companion_id,
                conversation_id,
                suggestion.topic.transition.value if suggestion.topic.transition is not None else None,
                suggestion.topic.topic_id,
            )
            if not should_send:
                await self._schedule_memory_summary(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    appended.message.id,
                )
                await self._schedule_state_maintenance(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    appended.message.id,
                )
                await self._record_executed_state(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    decision.id,
                    appended.message.id,
                    suggestion,
                    action,
                    should_send,
                    validation,
                    user_spoke=True,
                )
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            message_id = uuid.uuid4()
            yield MessageStarted(
                turn_id=turn_id,
                message_id=message_id,
                role="companion",
                sequence=sequence.next(),
            )
            if validation.get("fallback"):
                parts.append(FALLBACK_USER_TEXT)
                yield MessageDelta(
                    turn_id=turn_id,
                    message_id=message_id,
                    delta=FALLBACK_USER_TEXT,
                    index=0,
                    sequence=sequence.next(),
                )
            else:
                index = 0
                try:
                    async for piece in self._realize_pieces(
                        suggestion,
                        context,
                        _scope_for(scope, decision.id),
                    ):
                        parts.append(piece)
                        yield MessageDelta(
                            turn_id=turn_id,
                            message_id=message_id,
                            delta=piece,
                            index=index,
                            sequence=sequence.next(),
                        )
                        index += 1
                except ModelAdapterError as exc:
                    if not parts:
                        parts.append(FALLBACK_USER_TEXT)
                        yield MessageDelta(
                            turn_id=turn_id,
                            message_id=message_id,
                            delta=FALLBACK_USER_TEXT,
                            index=0,
                            sequence=sequence.next(),
                        )
                    else:
                        await abandon(DecisionStatus.FAILED)
                        logger.info("realization failed for decision %s trace_id=%s", decision_id, trace_id)
                        yield TurnFailed(turn_id=turn_id, error=failure_for(exc), sequence=sequence.next())
                        return
            text = "".join(parts).strip()
            if not text:
                await abandon(DecisionStatus.FAILED)
                yield TurnFailed(
                    turn_id=turn_id,
                    error=TurnErrorBody(code="MODEL_OUTPUT_INVALID", message="模型输出不可用", retryable=False),
                    sequence=sequence.next(),
                )
                return
            await self._dialogue.complete_sent_message(
                session,
                user_id,
                companion_id,
                decision.id,
                message_id=message_id,
                content=text,
            )
            await self._schedule_memory_summary(
                session,
                user_id,
                companion_id,
                conversation_id,
                appended.message.id,
            )
            await self._schedule_state_maintenance(
                session,
                user_id,
                companion_id,
                conversation_id,
                appended.message.id,
            )
            await self._record_executed_state(
                session,
                user_id,
                companion_id,
                conversation_id,
                decision.id,
                appended.message.id,
                suggestion,
                action,
                should_send,
                validation,
                user_spoke=True,
            )
            settled = True
            yield MessageCompleted(
                turn_id=turn_id,
                message_id=message_id,
                finish_reason="stop",
                sequence=sequence.next(),
            )
            yield TurnCompleted(turn_id=turn_id, outcome="replied", sequence=sequence.next())
        except (asyncio.CancelledError, GeneratorExit):
            await abandon(DecisionStatus.CANCELLED)
            raise
        except Exception as exc:
            logger.exception("user turn failed trace_id=%s", trace_id)
            await abandon(DecisionStatus.FAILED)
            if sequence.value == 0:
                raise
            yield TurnFailed(turn_id=turn_id, error=failure_for(exc), sequence=sequence.next())

    async def _replay_turn(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        decision: DialogueDecision,
    ) -> AsyncIterator[TurnStreamEvent]:
        sequence = _Sequence()
        yield TurnStarted(turn_id=decision.id, conversation_id=conversation_id, sequence=sequence.next())
        if decision.status != DecisionStatus.COMPLETED.value:
            yield TurnFailed(
                turn_id=decision.id,
                error=TurnErrorBody(code="DECISION_FAILED", message="这次交流没有完成", retryable=False),
                sequence=sequence.next(),
            )
            return
        if decision.primary_action == DialogueAction.QUIET.value or decision.result_message_id is None:
            yield TurnCompleted(turn_id=decision.id, outcome="quiet", sequence=sequence.next())
            return
        message = await self._conversations.get_owned_message(
            session,
            user_id,
            companion_id,
            decision.result_message_id,
        )
        yield MessageStarted(
            turn_id=decision.id,
            message_id=message.id,
            role="companion",
            sequence=sequence.next(),
        )
        yield MessageDelta(
            turn_id=decision.id,
            message_id=message.id,
            delta=message.content,
            index=0,
            sequence=sequence.next(),
        )
        yield MessageCompleted(
            turn_id=decision.id,
            message_id=message.id,
            finish_reason="stop",
            sequence=sequence.next(),
        )
        yield TurnCompleted(turn_id=decision.id, outcome="replied", sequence=sequence.next())

    async def _realize_pieces(
        self,
        suggestion: ModelDecisionSuggestion,
        context: TurnContext,
        scope: ModelCallScope,
    ) -> AsyncIterator[str]:
        messages = context.realization_input(suggestion)
        stream_text = getattr(self._adapter, "stream_text", None)
        if stream_text is not None:
            async for piece in stream_text(ModelConfigKey.CONVERSATION, messages, scope):
                if piece:
                    yield piece
            return
        completion = await self._adapter.complete_text(ModelConfigKey.CONVERSATION, messages, scope)
        content = completion.content.strip()
        if content:
            yield content

    async def _schedule_memory_extract(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> None:
        await self._tasks.create(
            session,
            CreateBackgroundTaskRequest(
                user_id=user_id,
                companion_id=companion_id,
                task_type=BackgroundTaskType.MEMORY_EXTRACT,
                task_key=f"memory-extract:{message_id}",
                queue_name="memory",
                payload={
                    "user_id": str(user_id),
                    "message_id": str(message_id),
                    "conversation_id": str(conversation_id),
                },
                max_retries=2,
                scheduled_at=datetime.now(UTC),
            ),
        )

    async def _schedule_memory_summary(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> None:
        await self._tasks.create(
            session,
            CreateBackgroundTaskRequest(
                user_id=user_id,
                companion_id=companion_id,
                task_type=BackgroundTaskType.MEMORY_SUMMARIZE,
                task_key=f"memory-summarize:{message_id}",
                queue_name="memory",
                payload={
                    "user_id": str(user_id),
                    "message_id": str(message_id),
                    "conversation_id": str(conversation_id),
                },
                max_retries=2,
                scheduled_at=datetime.now(UTC),
            ),
        )

    async def _schedule_state_maintenance(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> None:
        await self._tasks.create(
            session,
            CreateBackgroundTaskRequest(
                user_id=user_id,
                companion_id=companion_id,
                task_type=BackgroundTaskType.STATE_MAINTENANCE,
                task_key=f"state-maintenance:{message_id}",
                queue_name="state",
                payload={
                    "user_id": str(user_id),
                    "message_id": str(message_id),
                    "conversation_id": str(conversation_id),
                },
                max_retries=2,
                scheduled_at=datetime.now(UTC),
            ),
        )

    async def iter_proactive_turn(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
    ) -> AsyncIterator[TurnStreamEvent]:
        turn_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        sequence = _Sequence()
        parts: list[str] = []
        message_id: uuid.UUID | None = None
        decision_id: uuid.UUID | None = None
        settled = False

        async def abandon(status: DecisionStatus) -> None:
            nonlocal settled
            if settled or decision_id is None:
                return
            await self._dialogue.close_unfinished(
                session,
                user_id,
                companion_id,
                decision_id,
                final_status=status,
                message_id=message_id,
                content="".join(parts),
            )
            settled = True

        try:
            state = await self._states.get_current(session, user_id, companion_id)
            interaction = InteractionState.model_validate(state.interaction)
            yield TurnStarted(turn_id=turn_id, conversation_id=conversation_id, sequence=sequence.next())
            if not interaction.proactive_allowed or interaction.mode not in _PROACTIVE_MODES:
                suggestion = blocked_proactive()
                decision = await self._save(
                    session,
                    user_id,
                    companion_id,
                    TriggerType.PROACTIVE,
                    conversation_id,
                    None,
                    suggestion,
                    DialogueAction.QUIET,
                    False,
                    {"accepted": True, "blocked": "proactive_not_allowed"},
                    proposal={},
                    decision_id=turn_id,
                )
                decision_id = decision.id
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            context = await self._context(session, user_id, companion_id, conversation_id)
            scope = ModelCallScope(
                trace_id=trace_id,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                context_versions=context.versions or {},
            )
            suggestion, validation = await self._choose(context, scope, proactive_fallback)
            action, should_send = final_send(suggestion)
            if should_send and conversation_id is None:
                action = DialogueAction.QUIET
                should_send = False
                validation = {**validation, "should_send": False, "blocked": "missing_conversation"}
            decision = await self._save(
                session,
                user_id,
                companion_id,
                TriggerType.PROACTIVE,
                conversation_id,
                None,
                suggestion,
                action,
                should_send,
                validation,
                decision_id=turn_id,
            )
            decision_id = decision.id
            await self._link_calls(trace_id, decision.id)
            if conversation_id is not None:
                await self._contexts.record_topic_transition(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    suggestion.topic.transition.value if suggestion.topic.transition is not None else None,
                    suggestion.topic.topic_id,
                )
            if not should_send:
                await self._record_executed_state(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    decision.id,
                    None,
                    suggestion,
                    action,
                    should_send,
                    validation,
                    user_spoke=False,
                )
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            message_id = uuid.uuid4()
            index = 0
            started = False
            try:
                async for piece in self._realize_pieces(suggestion, context, _scope_for(scope, decision.id)):
                    if not started:
                        yield MessageStarted(
                            turn_id=turn_id,
                            message_id=message_id,
                            role="companion",
                            sequence=sequence.next(),
                        )
                        started = True
                    parts.append(piece)
                    yield MessageDelta(
                        turn_id=turn_id,
                        message_id=message_id,
                        delta=piece,
                        index=index,
                        sequence=sequence.next(),
                    )
                    index += 1
            except ModelAdapterError as exc:
                if parts:
                    await abandon(DecisionStatus.FAILED)
                    logger.info("proactive realization failed for decision %s trace_id=%s", decision_id, trace_id)
                    yield TurnFailed(turn_id=turn_id, error=failure_for(exc), sequence=sequence.next())
                    return
                await self._dialogue.suppress_unsent(
                    session,
                    user_id,
                    companion_id,
                    decision.id,
                    "realization_failed",
                )
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            text = "".join(parts).strip()
            if not text or conversation_id is None:
                if started:
                    await abandon(DecisionStatus.FAILED)
                    yield TurnFailed(
                        turn_id=turn_id,
                        error=TurnErrorBody(code="MODEL_OUTPUT_INVALID", message="模型输出不可用", retryable=False),
                        sequence=sequence.next(),
                    )
                    return
                await self._dialogue.suppress_unsent(
                    session,
                    user_id,
                    companion_id,
                    decision.id,
                    "empty_realization",
                )
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            await self._dialogue.complete_sent_message(
                session,
                user_id,
                companion_id,
                decision.id,
                message_id=message_id,
                content=text,
            )
            if conversation_id is not None:
                await self._schedule_memory_summary(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    message_id,
                )
                await self._schedule_state_maintenance(
                    session,
                    user_id,
                    companion_id,
                    conversation_id,
                    message_id,
                )
            await self._record_executed_state(
                session,
                user_id,
                companion_id,
                conversation_id,
                decision.id,
                message_id,
                suggestion,
                action,
                should_send,
                validation,
                user_spoke=False,
            )
            settled = True
            yield MessageCompleted(
                turn_id=turn_id,
                message_id=message_id,
                finish_reason="stop",
                sequence=sequence.next(),
            )
            yield TurnCompleted(turn_id=turn_id, outcome="replied", sequence=sequence.next())
        except (asyncio.CancelledError, GeneratorExit):
            await abandon(DecisionStatus.CANCELLED)
            raise
        except Exception as exc:
            logger.exception("proactive turn failed trace_id=%s", trace_id)
            await abandon(DecisionStatus.FAILED)
            if sequence.value == 0:
                raise
            yield TurnFailed(turn_id=turn_id, error=failure_for(exc), sequence=sequence.next())

    async def _context(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        current_message: str | None = None,
    ) -> TurnContext:
        _profile, version = await self._personas.get_current(session, user_id, companion_id)
        state = await self._states.get_current(session, user_id, companion_id)
        emotion = EmotionState.model_validate(state.emotion)
        relationship = RelationshipState.model_validate(state.relationship)
        interaction = InteractionState.model_validate(state.interaction)
        recent: list[dict[str, str]] = []
        if conversation_id is not None:
            messages = await self._conversations.list_messages(session, user_id, companion_id, conversation_id)
            recent = [{"sender_type": item.sender_type, "content": item.content} for item in messages]
        current = (current_message or "").strip()
        immediate = [{"content": current, "source": "current_message"}] if current else []
        memories = await self._retrieval.retrieve(session, user_id, companion_id, current)
        working = None
        if conversation_id is not None:
            working = await self._contexts.working_for_turn(session, user_id, companion_id, conversation_id)
        topics = await self._contexts.active_attention_context(session, user_id, companion_id)
        working_version = None if working is None else working.get("version")
        return TurnContext(
            mbti_type=version.mbti_type,
            core_traits=dict(version.core_traits),
            communication_preferences=dict(version.communication_preferences),
            emotion_primary=emotion.primary,
            emotion_cause=emotion.cause_summary,
            relationship_summary=relationship.summary,
            interaction_mode=interaction.mode.value,
            proactive_allowed=interaction.proactive_allowed,
            recent_messages=recent,
            memories=memories,
            immediate_facts=immediate,
            working_memory=working,
            attention_topics=topics,
            archive=dict(version.archive) if isinstance(version.archive, dict) else None,
            versions={
                "persona_version_id": str(version.id),
                "persona_version": str(version.version_number),
                "state_version": str(state.version),
                **({} if working_version is None else {"working_memory_version": str(working_version)}),
            },
        )

    async def _choose(
        self,
        context: TurnContext,
        scope: ModelCallScope,
        fallback: Callable[[], ModelDecisionSuggestion],
    ) -> tuple[ModelDecisionSuggestion, dict[str, object]]:
        try:
            suggestion = await self._ask(context.decision_input(False), scope)
        except ModelOutputError:
            try:
                suggestion = await self._ask(context.decision_input(True), scope)
            except ModelAdapterError as exc:
                return fallback(), {"accepted": False, "fallback": True, "error": exc.code}
        except ModelAdapterError as exc:
            return fallback(), {"accepted": False, "fallback": True, "error": exc.code}
        return suggestion, {"accepted": True, "fallback": False, "source": "model"}

    async def _ask(self, messages: list[ChatMessage], scope: ModelCallScope) -> ModelDecisionSuggestion:
        return await self._adapter.complete_structured(
            ModelConfigKey.DECISION,
            messages,
            ModelDecisionSuggestion,
            scope,
        )

    async def _save(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        trigger_type: TriggerType,
        conversation_id: uuid.UUID | None,
        trigger_message_id: uuid.UUID | None,
        suggestion: ModelDecisionSuggestion,
        action: DialogueAction,
        should_send: bool,
        validation: dict[str, object],
        proposal: dict[str, object] | None = None,
        decision_id: uuid.UUID | None = None,
    ) -> DialogueDecision:
        return await self._dialogue.save_validated_decision(
            session,
            user_id,
            companion_id,
            trigger_type=trigger_type,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            primary_action=action,
            secondary_actions=suggestion.secondary_actions,
            motivation=suggestion.motivation,
            topic=suggestion.topic,
            confidence=suggestion.confidence,
            reasoning_summary=suggestion.reasoning_summary,
            model_proposal=suggestion.model_dump(mode="json") if proposal is None else proposal,
            validation_result=validation,
            should_send=should_send,
            decision_id=decision_id,
        )

    async def _record_executed_state(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        decision_id: uuid.UUID,
        message_id: uuid.UUID | None,
        suggestion: ModelDecisionSuggestion,
        action: DialogueAction,
        should_send: bool,
        validation: dict[str, object],
        *,
        user_spoke: bool,
    ) -> None:
        if validation.get("blocked"):
            return
        try:
            current = await self._states.get_current(session, user_id, companion_id)
            plan = plan_turn_state(
                action=action,
                secondary_actions=list(suggestion.secondary_actions),
                should_send=should_send,
                fallback=bool(validation.get("fallback")),
                blocked=False,
                confidence=float(suggestion.confidence),
                emotion=EmotionState.model_validate(current.emotion),
                relationship=RelationshipState.model_validate(current.relationship),
                interaction=InteractionState.model_validate(current.interaction),
                motivation=MotivationState.model_validate(current.motivation),
                user_spoke=user_spoke,
                now=datetime.now(UTC),
            )
            if plan is None:
                return
            await self._states.apply_change(
                session,
                user_id,
                companion_id,
                ApplyStateChangeRequest(
                    expected_version=current.version,
                    source_type=StateSourceType.DIALOGUE_DECISION,
                    reason=plan.reason,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    dialogue_decision_id=decision_id,
                    emotion=plan.emotion,
                    relationship=plan.relationship,
                    interaction=plan.interaction,
                    motivation=plan.motivation,
                ),
            )
        except AppError as exc:
            logger.info("turn state was not written for decision %s: %s", decision_id, exc.message)
        except Exception:
            logger.exception("turn state update failed for decision %s", decision_id)

    async def _link_calls(self, trace_id: uuid.UUID, decision_id: uuid.UUID) -> None:
        try:
            await self._logs.attach_decision(trace_id, decision_id)
        except Exception:
            logger.exception("failed to link model calls trace_id=%s decision_id=%s", trace_id, decision_id)


_PROACTIVE_MODES = {InteractionMode.AVAILABLE, InteractionMode.WAITING}


def _scope_for(scope: ModelCallScope, decision_id: uuid.UUID) -> ModelCallScope:
    return scope.model_copy(update={"dialogue_decision_id": decision_id})


class _Sequence:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        current = self.value
        self.value += 1
        return current


def _default_adapter() -> DecisionModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
