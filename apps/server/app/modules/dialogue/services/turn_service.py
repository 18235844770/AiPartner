import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from anyio import CancelScope
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import CreateMessageRequest
from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.repositories.models import Message
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
from app.modules.dialogue.domain.expression_decoration import decorate_reply
from app.modules.dialogue.domain.message_burst import (
    MAX_MESSAGES,
    present_companion_message,
    split_companion_messages,
    take_completed_sentence,
)
from app.modules.dialogue.domain.speech_turn import (
    build_turn_shape,
    current_user_text,
    is_user_closing,
    speech_issues,
    speech_repair_message,
)
from app.modules.dialogue.domain.enums import DecisionStatus, DialogueAction, TriggerType
from app.modules.dialogue.domain.proactive import speak_when_user_is_absent
from app.modules.dialogue.domain.quiet_policy import align_user_closing, apply_quiet_gate
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
from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType, ModelConfigKey
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.model_call_log_service import ModelCallLogService
from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelOutputError
from app.modules.memory.services.context_service import MemoryContextService
from app.modules.memory.services.retrieval import MemoryRetrievalService
from app.modules.model_adapter.domain.messages import ChatMessage, TextCompletion
from app.modules.model_adapter.services.model_adapter import ModelCallScope
from app.modules.persona.domain.archive import AttachmentDisposition, PersonaArchive, RelationshipSelfAssertion
from app.modules.persona.services.persona_service import PersonaService
from app.modules.state.api.schemas import ApplyStateChangeRequest
from app.modules.state.domain.emotion import levels_summary
from app.modules.state.domain.enums import InteractionEnergy, InteractionMode, StateSourceType
from app.modules.state.domain.snapshots import EmotionState, InteractionState, MotivationState, RelationshipState
from app.modules.state.services.state_service import StateService
from app.shared.exceptions.errors import AppError
from app.shared.speech_marks import strip_non_speech_marks

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
    interaction_energy: str = "normal"
    current_local_time: str | None = None
    emotion_detail: dict[str, object] | None = None
    relationship_detail: dict[str, object] | None = None
    consecutive_quiet_turns: int = 0
    turn_kind: str = "user"

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
            interaction_energy=self.interaction_energy,
            current_local_time=self.current_local_time,
            emotion_detail=self.emotion_detail,
            relationship_detail=self.relationship_detail,
            turn_kind=self.turn_kind,
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
            interaction_energy=self.interaction_energy,
            current_local_time=self.current_local_time,
            emotion_detail=self.emotion_detail,
            relationship_detail=self.relationship_detail,
            turn_kind=self.turn_kind,
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
        *,
        managed_decision_id: uuid.UUID | None = None,
        public_turn_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[TurnStreamEvent, None]:
        turn_id = managed_decision_id or uuid.uuid4()
        trace_id = uuid.uuid4()
        sequence = _Sequence()
        delivery = _ReplyDelivery(first_message_id=uuid.uuid4())
        partial: _PartialRealization | None = None
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
                message_id=delivery.first_message_id if partial else None,
                content=partial.text if partial else None,
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
                if managed_decision_id is None:
                    existing = await self._dialogue.find_by_trigger_message(
                        session, user_id, companion_id, appended.message.id,
                    )
                else:
                    existing = await self._dialogue.find_owned_decision(
                        session, user_id, companion_id, managed_decision_id,
                    )
                if existing is not None:
                    settled = True
                    async for event in self._replay_turn(session, user_id, companion_id, conversation_id, existing):
                        yield event
                    return
            yield TurnStarted(turn_id=turn_id, conversation_id=conversation_id, sequence=sequence.next())
            context_options = {"through_user_sequence": appended.message.sequence_number} if managed_decision_id else {}
            context = await self._context(session, user_id, companion_id, conversation_id, content, **context_options)
            scope = ModelCallScope(
                trace_id=trace_id,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                context_versions=context.versions or {},
            )
            suggestion, validation = await self._choose(context, scope, user_fallback)
            if managed_decision_id is not None and validation.get("fallback"):
                yield TurnFailed(
                    turn_id=turn_id, sequence=sequence.next(),
                    error=TurnErrorBody(code="MODEL_REQUEST_FAILED", message="模型服务暂时不可用", retryable=True),
                )
                return
            suggestion, gate = apply_quiet_gate(
                suggestion,
                user_message=content,
                consecutive_quiet=context.consecutive_quiet_turns,
                user_triggered=True,
            )
            suggestion, aligned = align_user_closing(suggestion, content)
            validation = {**validation, **gate, **aligned}
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
                    user_message=content,
                )
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            bubbles = self._realize_bubbles(
                suggestion,
                context,
                _scope_for(scope, decision.id),
                user_triggered=True,
                decision_fallback=bool(validation.get("fallback")),
                strict_model=managed_decision_id is not None,
            )
            delivery_options = {"public_turn_id": public_turn_id} if public_turn_id is not None else {}
            async with aclosing(self._deliver_reply(
                session, user_id, companion_id, turn_id, sequence, delivery, bubbles, **delivery_options,
            )) as events:
                async for event in events:
                    yield event
            if delivery.last_sent_at is None:
                raise ModelOutputError("empty realization")
            await self._dialogue.finish_sent_turn(session, user_id, companion_id, decision.id)
            settled = True
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
                user_message=content,
            )
            yield TurnCompleted(turn_id=turn_id, outcome="replied", sequence=sequence.next())
        except _PartialRealization as exc:
            partial = exc
            await abandon(DecisionStatus.FAILED)
            for event in sequence.message_events(turn_id, delivery.first_message_id, exc.text, completed=False):
                yield event
            logger.info("realization failed for decision %s trace_id=%s", decision_id, trace_id)
            yield TurnFailed(turn_id=turn_id, error=failure_for(exc.cause), sequence=sequence.next())
        except (asyncio.CancelledError, GeneratorExit):
            with CancelScope(shield=True):
                await abandon(DecisionStatus.CANCELLED)
            raise
        except Exception as exc:
            if managed_decision_id is None:
                logger.exception("user turn failed trace_id=%s", trace_id)
            else:
                logger.warning("account turn failed trace_id=%s (%s)", trace_id, type(exc).__name__)
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
        messages = await self._sent_burst(
            session,
            user_id,
            companion_id,
            conversation_id,
            decision,
        )
        for message in messages:
            for event in sequence.message_events(decision.id, message.id, message.content):
                yield event
        yield TurnCompleted(turn_id=decision.id, outcome="replied", sequence=sequence.next())

    async def _sent_burst(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        decision: DialogueDecision,
    ) -> list[Message]:
        if decision.result_message_id is None:
            return []
        anchor = await self._conversations.get_owned_message(
            session,
            user_id,
            companion_id,
            decision.result_message_id,
        )
        listed = await self._conversations.list_messages(session, user_id, companion_id, conversation_id)
        group = str(decision.id)
        grouped = [
            item
            for item in listed
            if str((item.metadata_ or {}).get("delivery_group") or "") == group
        ]
        return grouped or [anchor]

    async def _deliver_reply(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        turn_id: uuid.UUID,
        sequence: "_Sequence",
        delivery: "_ReplyDelivery",
        bubbles: AsyncGenerator[str, None],
        *,
        public_turn_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[TurnStreamEvent, None]:
        loop = asyncio.get_running_loop()
        async with aclosing(bubbles):
            async for bubble in bubbles:
                if delivery.last_sent_at is None:
                    message_id = delivery.first_message_id
                else:
                    remaining = _MIN_MESSAGE_GAP_SECONDS - (loop.time() - delivery.last_sent_at)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                    message_id = uuid.uuid4()
                options = {"public_turn_id": public_turn_id} if public_turn_id is not None else {}
                await self._dialogue.record_sent_message(
                    session, user_id, companion_id, turn_id, message_id=message_id, content=bubble, **options,
                )
                delivery.last_sent_at = loop.time()
                for event in sequence.message_events(turn_id, message_id, bubble):
                    yield event

    async def _realize_bubbles(
        self,
        suggestion: ModelDecisionSuggestion,
        context: TurnContext,
        scope: ModelCallScope,
        *,
        user_triggered: bool = False,
        decision_fallback: bool = False,
        strict_model: bool = False,
    ) -> AsyncGenerator[str, None]:
        if decision_fallback:
            yield present_companion_message(FALLBACK_USER_TEXT)
            return
        messages = context.realization_input(suggestion)
        user_text = current_user_text(context.immediate_facts, context.recent_messages)
        action = suggestion.primary_action.value
        shape = build_turn_shape(action, user_text)
        ownership = (
            suggestion.emotional_motivation.ownership.value if suggestion.emotional_motivation is not None else None
        )

        def check(text: str) -> list[str]:
            return speech_issues(text, shape, user_text, emotion_ownership=ownership)

        def decorate(text: str) -> str:
            return decorate_reply(
                text,
                mbti_type=context.mbti_type,
                emotion=context.emotion_primary,
                action=action,
                user_text=user_text,
                recent_messages=context.recent_messages,
                fact_correct=suggestion.fact_check.should_correct,
                strong=_emotion_is_strong(context.emotion_detail, context.emotion_primary, suggestion),
            )

        sent: list[str] = []
        pending = ""
        early_message_limit = min(MAX_MESSAGES - 1, shape.max_sentences - 1)
        can_split = (
            getattr(self._adapter, "stream_text", None) is not None
            and not is_user_closing(user_text)
        )
        try:
            async with aclosing(self._stream_realization(messages, scope)) as stream:
                async for piece in stream:
                    pending += piece
                    while can_split and len(sent) < early_message_limit:
                        segment = take_completed_sentence(pending)
                        if segment is None:
                            break
                        sentence, rest = segment
                        if check("".join(sent) + sentence):
                            can_split = False
                            break
                        spoken = decorate(sentence) if not sent else strip_non_speech_marks(sentence)
                        bubble = present_companion_message(spoken)
                        if not bubble:
                            break
                        sent.append(sentence)
                        pending = rest
                        yield bubble
        except ModelAdapterError as exc:
            if pending.strip() and not sent:
                raise _PartialRealization(pending.strip(), exc) from exc
            if sent or not user_triggered or strict_model:
                raise
            yield present_companion_message(FALLBACK_USER_TEXT)
            return

        if not pending.strip():
            return
        prefix = "".join(sent)
        text = pending.strip()
        issues = check(prefix + pending)
        if issues:
            logger.info("speech rewrite issues=%s", issues)
            repair = speech_repair_message(issues, sent_prefix=prefix)
            repaired = [
                *messages,
                ChatMessage(role="assistant", content=prefix + pending),
                ChatMessage(role="user", content=repair),
            ]
            try:
                async with aclosing(self._stream_realization(repaired, scope)) as stream:
                    second = "".join([piece async for piece in stream]).strip()
            except ModelAdapterError:
                logger.info("speech rewrite failed")
                second = ""
            if sent and (not second or check(prefix + second)):
                raise ModelOutputError("reply continuation did not pass speech checks")
            if second:
                text = second
                again = check(prefix + second)
                if again:
                    logger.info("speech turn kept after rewrite issues=%s", again)

        if sent:
            remaining = present_companion_message(strip_non_speech_marks(text))
            if remaining:
                yield remaining
        else:
            for bubble in split_companion_messages(decorate(text)):
                yield bubble

    async def _stream_realization(
        self, messages: list[ChatMessage], scope: ModelCallScope,
    ) -> AsyncGenerator[str, None]:
        stream_text = getattr(self._adapter, "stream_text", None)
        if stream_text is not None:
            async with aclosing(stream_text(ModelConfigKey.CONVERSATION, messages, scope)) as stream:
                async for piece in stream:
                    if piece:
                        yield piece
        else:
            completion = await self._adapter.complete_text(ModelConfigKey.CONVERSATION, messages, scope)
            yield completion.content

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
        *,
        managed_decision_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[TurnStreamEvent, None]:
        turn_id = managed_decision_id or uuid.uuid4()
        trace_id = uuid.uuid4()
        sequence = _Sequence()
        delivery = _ReplyDelivery(first_message_id=uuid.uuid4())
        partial: _PartialRealization | None = None
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
                message_id=delivery.first_message_id if partial else None,
                content=partial.text if partial else None,
            )
            settled = True

        try:
            if managed_decision_id is not None and conversation_id is not None:
                existing = await self._dialogue.find_owned_decision(
                    session, user_id, companion_id, managed_decision_id,
                )
                if existing is not None:
                    async for event in self._replay_turn(session, user_id, companion_id, conversation_id, existing):
                        yield event
                    return
            state = await self._states.get_current(session, user_id, companion_id)
            interaction = InteractionState.model_validate(state.interaction)
            yield TurnStarted(turn_id=turn_id, conversation_id=conversation_id, sequence=sequence.next())
            if (
                not interaction.proactive_allowed
                or interaction.mode not in _PROACTIVE_MODES
                or interaction.energy == InteractionEnergy.QUIET
            ):
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
            context_options = {"through_user_sequence": 2**63 - 1} if managed_decision_id is not None else {}
            context = await self._context(
                session,
                user_id,
                companion_id,
                conversation_id,
                turn_kind="proactive",
                **context_options,
            )
            scope = ModelCallScope(
                trace_id=trace_id,
                user_id=user_id,
                companion_id=companion_id,
                conversation_id=conversation_id,
                context_versions=context.versions or {},
            )
            suggestion, validation = await self._choose(context, scope, proactive_fallback)
            if validation.get("accepted") and not validation.get("fallback"):
                suggestion, gate = speak_when_user_is_absent(suggestion)
                validation = {**validation, **gate}
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
            bubbles = self._realize_bubbles(suggestion, context, _scope_for(scope, decision.id))
            unsent_reason = "empty_realization"
            try:
                async with aclosing(self._deliver_reply(
                    session, user_id, companion_id, turn_id, sequence, delivery, bubbles,
                )) as events:
                    async for event in events:
                        yield event
            except ModelAdapterError:
                if delivery.last_sent_at is not None:
                    raise
                unsent_reason = "realization_failed"
            if delivery.last_sent_at is None:
                await self._dialogue.suppress_unsent(session, user_id, companion_id, decision.id, unsent_reason)
                settled = True
                yield TurnCompleted(turn_id=turn_id, outcome="quiet", sequence=sequence.next())
                return
            await self._dialogue.finish_sent_turn(session, user_id, companion_id, decision.id)
            settled = True
            message_id = delivery.first_message_id
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
            yield TurnCompleted(turn_id=turn_id, outcome="replied", sequence=sequence.next())
        except _PartialRealization as exc:
            partial = exc
            await abandon(DecisionStatus.FAILED)
            for event in sequence.message_events(turn_id, delivery.first_message_id, exc.text, completed=False):
                yield event
            logger.info("realization failed for decision %s trace_id=%s", decision_id, trace_id)
            yield TurnFailed(turn_id=turn_id, error=failure_for(exc.cause), sequence=sequence.next())
        except (asyncio.CancelledError, GeneratorExit):
            with CancelScope(shield=True):
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
        turn_kind: str = "user",
        through_user_sequence: int | None = None,
    ) -> TurnContext:
        _profile, version = await self._personas.get_current(session, user_id, companion_id)
        core_traits = dict(version.core_traits)
        if through_user_sequence is not None:
            companion = await IdentityService().get_owned_companion(session, user_id, companion_id)
            core_traits["companion_name"] = companion.name
        state = await self._states.get_current(session, user_id, companion_id)
        emotion = EmotionState.model_validate(state.emotion)
        relationship = RelationshipState.model_validate(state.relationship)
        interaction = InteractionState.model_validate(state.interaction)
        recent: list[dict[str, str]] = []
        if conversation_id is not None:
            if through_user_sequence is None:
                messages = await self._conversations.list_messages(session, user_id, companion_id, conversation_id)
            else:
                messages = await self._conversations.list_turn_context(
                    session, user_id, companion_id, conversation_id, through_user_sequence,
                )
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
            core_traits=core_traits,
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
            interaction_energy=interaction.energy.value,
            current_local_time=datetime.now().astimezone().isoformat(timespec="minutes"),
            emotion_detail={
                "jealousy": emotion.jealousy,
                "possessiveness": emotion.possessiveness,
                "emotional_tension": emotion.emotional_tension,
                "triggers": list(emotion.triggers),
                "levels": dict(emotion.levels),
                "summary": levels_summary(emotion.levels),
            },
            relationship_detail={
                "attachment_strength": relationship.attachment_strength,
                "emotional_reliance": relationship.emotional_reliance,
                "relationship_security": relationship.relationship_security,
                "perceived_specialness": relationship.perceived_specialness,
                "separation_sensitivity": relationship.separation_sensitivity,
                "reassurance_satisfaction": relationship.reassurance_satisfaction,
                "closeness_desire": relationship.closeness_desire,
                "exclusivity_need": relationship.exclusivity_need,
            },
            consecutive_quiet_turns=interaction.consecutive_quiet_turns,
            turn_kind=turn_kind,
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
        user_message: str | None = None,
    ) -> None:
        if validation.get("blocked"):
            return
        try:
            current = await self._states.get_current(session, user_id, companion_id)
            disposition, self_assertion = await self._relationship_tendencies(session, user_id, companion_id)
            relationship_kind = None
            if suggestion.relationship_motivation is not None:
                relationship_kind = suggestion.relationship_motivation.kind
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
                disposition=disposition,
                self_assertion=self_assertion,
                self_motivation_kind=suggestion.self_motivation.kind,
                relationship_motivation_kind=relationship_kind,
                user_message=user_message,
                emotion_ownership=(
                    suggestion.emotional_motivation.ownership.value
                    if suggestion.emotional_motivation is not None
                    else None
                ),
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

    async def _relationship_tendencies(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> tuple[AttachmentDisposition | None, RelationshipSelfAssertion | None]:
        try:
            _profile, version = await self._personas.get_current(session, user_id, companion_id)
        except AppError:
            return None, None
        archive = version.archive if isinstance(version.archive, dict) else None
        if not archive:
            return None, None
        try:
            relationship = PersonaArchive.model_validate(archive).relationship
            return relationship.attachment_disposition, relationship.self_assertion
        except ValidationError:
            raw = archive.get("relationship")
            if not isinstance(raw, dict):
                return None, None
            disposition = None
            assertion = None
            raw_disposition = raw.get("attachment_disposition")
            if isinstance(raw_disposition, dict):
                try:
                    disposition = AttachmentDisposition.model_validate(raw_disposition)
                except ValidationError:
                    disposition = None
            raw_assertion = raw.get("self_assertion")
            if isinstance(raw_assertion, dict):
                try:
                    assertion = RelationshipSelfAssertion.model_validate(raw_assertion)
                except ValidationError:
                    assertion = None
            return disposition, assertion

    async def _link_calls(self, trace_id: uuid.UUID, decision_id: uuid.UUID) -> None:
        try:
            await self._logs.attach_decision(trace_id, decision_id)
        except Exception:
            logger.exception("failed to link model calls trace_id=%s decision_id=%s", trace_id, decision_id)


_PROACTIVE_MODES = {InteractionMode.AVAILABLE, InteractionMode.WAITING}
_MIN_MESSAGE_GAP_SECONDS = 0.65


@dataclass
class _ReplyDelivery:
    first_message_id: uuid.UUID
    last_sent_at: float | None = None


class _PartialRealization(Exception):
    """流式生成中途失败。已收到的文字还没通过口语检查，不能当成完成。"""

    def __init__(self, text: str, cause: ModelAdapterError) -> None:
        self.text = text
        self.cause = cause


def _emotion_is_strong(
    emotion_detail: dict[str, object] | None,
    emotion_primary: str,
    suggestion: ModelDecisionSuggestion,
) -> bool:
    motive = suggestion.emotional_motivation
    if motive is not None and motive.intensity >= 0.7:
        return True
    detail = emotion_detail or {}
    levels = detail.get("levels")
    if not isinstance(levels, dict):
        return False
    level = levels.get(emotion_primary, 0)
    return isinstance(level, (int, float)) and not isinstance(level, bool) and float(level) >= 70


def _scope_for(scope: ModelCallScope, decision_id: uuid.UUID) -> ModelCallScope:
    return scope.model_copy(update={"dialogue_decision_id": decision_id})


class _Sequence:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        current = self.value
        self.value += 1
        return current

    def message_events(
        self, turn_id: uuid.UUID, message_id: uuid.UUID, text: str, *, completed: bool = True,
    ) -> Iterator[TurnStreamEvent]:
        yield MessageStarted(turn_id=turn_id, message_id=message_id, role="companion", sequence=self.next())
        yield MessageDelta(turn_id=turn_id, message_id=message_id, delta=text, index=0, sequence=self.next())
        if completed:
            yield MessageCompleted(turn_id=turn_id, message_id=message_id, finish_reason="stop", sequence=self.next())


def _default_adapter() -> DecisionModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
