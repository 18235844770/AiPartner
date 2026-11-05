import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import CreateMessageRequest
from app.modules.conversation.domain.enums import SenderType
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.api.schemas import RealizeDecisionRequest
from app.modules.dialogue.domain.context import decision_messages, final_send, realization_messages
from app.modules.dialogue.domain.enums import DialogueAction, TriggerType
from app.modules.dialogue.domain.suggestion import (
    FALLBACK_USER_TEXT,
    ModelDecisionSuggestion,
    blocked_proactive,
    proactive_fallback,
    user_fallback,
)
from app.modules.dialogue.repositories.models import DialogueDecision
from app.modules.dialogue.services.dialogue_service import DialogueService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType, ModelConfigKey
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelOutputError
from app.modules.memory.services.retrieval import MemoryRetrievalService
from app.modules.model_adapter.domain.messages import ChatMessage, TextCompletion
from app.modules.model_adapter.services.model_adapter import ModelCallScope
from app.modules.persona.services.persona_service import PersonaService
from app.modules.state.domain.enums import InteractionMode
from app.modules.state.domain.snapshots import EmotionState, InteractionState, RelationshipState
from app.modules.state.services.state_service import StateService

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
        )


@dataclass(frozen=True)
class TurnResult:
    user_message_id: uuid.UUID | None
    decision: DialogueDecision
    replay: bool


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
    ) -> None:
        self._dialogue = dialogue or DialogueService()
        self._conversations = conversations or ConversationService()
        self._personas = personas or PersonaService()
        self._states = states or StateService()
        self._adapter = adapter if adapter is not None else _default_adapter()
        self._tasks = tasks or BackgroundTaskService()
        self._retrieval = retrieval or MemoryRetrievalService()

    async def respond_to_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        client_message_id: uuid.UUID | None = None,
    ) -> TurnResult:
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
                return TurnResult(appended.message.id, existing, True)
        context = await self._context(session, user_id, companion_id, conversation_id, content)
        trace_id = uuid.uuid4()
        scope = ModelCallScope(
            trace_id=trace_id,
            user_id=user_id,
            companion_id=companion_id,
            conversation_id=conversation_id,
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
        )
        if should_send:
            text = FALLBACK_USER_TEXT
            if not validation.get("fallback"):
                text = await self._realize_text(suggestion, context, _scope_for(scope, decision.id), FALLBACK_USER_TEXT)
            decision = await self._dialogue.realize(
                session,
                user_id,
                companion_id,
                decision.id,
                RealizeDecisionRequest(content=text),
            )
        return TurnResult(appended.message.id, decision, False)

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

    async def consider_proactive(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
    ) -> TurnResult:
        state = await self._states.get_current(session, user_id, companion_id)
        interaction = InteractionState.model_validate(state.interaction)
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
            )
            return TurnResult(None, decision, False)
        context = await self._context(session, user_id, companion_id, conversation_id)
        scope = ModelCallScope(
            trace_id=uuid.uuid4(),
            user_id=user_id,
            companion_id=companion_id,
            conversation_id=conversation_id,
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
        )
        if not should_send:
            return TurnResult(None, decision, False)
        try:
            text = await self._realize_text(suggestion, context, _scope_for(scope, decision.id), None)
        except ModelAdapterError:
            logger.info("proactive realization failed for decision %s", decision.id)
            decision = await self._dialogue.suppress_unsent(
                session,
                user_id,
                companion_id,
                decision.id,
                "realization_failed",
            )
            return TurnResult(None, decision, False)
        decision = await self._dialogue.realize(
            session,
            user_id,
            companion_id,
            decision.id,
            RealizeDecisionRequest(content=text),
        )
        return TurnResult(None, decision, False)

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

    async def _realize_text(
        self,
        suggestion: ModelDecisionSuggestion,
        context: TurnContext,
        scope: ModelCallScope,
        fallback_text: str | None,
    ) -> str:
        try:
            completion = await self._adapter.complete_text(
                ModelConfigKey.CONVERSATION,
                realization_messages(
                    suggestion,
                    context.recent_messages,
                    context.memories,
                    context.immediate_facts,
                ),
                scope,
            )
        except ModelAdapterError:
            if fallback_text is None:
                raise
            return fallback_text
        content = completion.content.strip()
        if not content:
            if fallback_text is None:
                raise ModelOutputError("模型没有返回文本")
            return fallback_text
        return content

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
        )


_PROACTIVE_MODES = {InteractionMode.AVAILABLE, InteractionMode.WAITING}


def _scope_for(scope: ModelCallScope, decision_id: uuid.UUID) -> ModelCallScope:
    return scope.model_copy(update={"dialogue_decision_id": decision_id})


def _default_adapter() -> DecisionModel:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
