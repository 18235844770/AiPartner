import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.api.schemas import CreateMessageRequest
from app.modules.conversation.domain.enums import MessageStatus, SenderType
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.api.schemas import DecisionResponse, RealizeDecisionRequest, RecordDecisionRequest
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DecisionStatus, DialogueAction, TriggerType
from app.modules.dialogue.repositories.dialogue_repository import DialogueRepository
from app.modules.dialogue.repositories.models import DialogueDecision
from app.modules.identity.services.identity_service import IdentityService
from app.modules.state.domain.enums import InteractionMode
from app.modules.state.domain.snapshots import InteractionState
from app.modules.state.services.state_service import StateService
from app.shared.exceptions.errors import AppError, ConflictError, NotFoundError

logger = logging.getLogger(__name__)

_PROACTIVE_MODES = {InteractionMode.AVAILABLE, InteractionMode.WAITING}


class DialogueService:
    def __init__(
        self,
        decisions: DialogueRepository | None = None,
        identity: IdentityService | None = None,
        conversations: ConversationService | None = None,
        states: StateService | None = None,
    ) -> None:
        self._decisions = decisions or DialogueRepository()
        self._identity = identity or IdentityService()
        self._conversations = conversations or ConversationService()
        self._states = states or StateService()

    async def record(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: RecordDecisionRequest,
    ) -> DialogueDecision:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            state = await self._states.get_current(session, user_id, companion_id)
            conversation_id = await self._resolve_conversation(session, user_id, companion_id, data)
            self._require_send_target(data, conversation_id)
            self._require_proactive_permission(data, state.interaction)
            now = datetime.now(UTC)
            quiet = data.primary_action == DialogueAction.QUIET
            decision = DialogueDecision(
                companion_id=companion_id,
                conversation_id=conversation_id,
                trigger_message_id=data.trigger_message_id,
                result_message_id=None,
                trigger_type=data.trigger_type.value,
                primary_action=data.primary_action.value,
                secondary_actions=[item.value for item in data.secondary_actions],
                motivation=data.motivation.model_dump(mode="json"),
                topic=data.topic.model_dump(mode="json"),
                model_proposal=data.model_dump(mode="json"),
                validation_result={"accepted": True, "should_send": not quiet},
                confidence=data.confidence,
                reasoning_summary=data.reasoning_summary,
                status=DecisionStatus.COMPLETED.value if quiet else DecisionStatus.APPROVED.value,
                created_at=now,
                completed_at=now if quiet else None,
            )
            await self._decisions.add(session, decision)
        logger.info("recorded decision %s action %s", decision.id, decision.primary_action)
        return decision

    async def get_decision(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
    ) -> DialogueDecision:
        if session.in_transaction():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require(session, decision_id, companion_id)
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._require(session, decision_id, companion_id)

    async def list_decisions(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[DialogueDecision]:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._decisions.list_for_companion(session, companion_id)

    async def realize(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        data: RealizeDecisionRequest,
    ) -> DialogueDecision:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            decision = await self._decisions.get_for_update(session, decision_id, companion_id)
            if decision is None:
                raise NotFoundError("决策不存在")
            if decision.primary_action == DialogueAction.QUIET.value:
                raise AppError("Quiet 不生成消息")
            if decision.status == DecisionStatus.COMPLETED.value:
                raise ConflictError("决策已经完成")
            if decision.status != DecisionStatus.APPROVED.value:
                raise AppError("决策当前不能生成消息")
            if decision.conversation_id is None:
                raise AppError("发送决策必须关联会话")
            result = await self._conversations.append_message(
                session,
                user_id,
                companion_id,
                decision.conversation_id,
                CreateMessageRequest(sender_type=SenderType.COMPANION, content=data.content),
            )
            decision.result_message_id = result.message.id
            decision.status = DecisionStatus.COMPLETED.value
            decision.completed_at = datetime.now(UTC)
        logger.info("realized decision %s as message %s", decision.id, decision.result_message_id)
        return decision

    async def complete_sent_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        *,
        message_id: uuid.UUID,
        content: str,
    ) -> DialogueDecision:
        if session.in_transaction():
            decision = await self._complete_sent_message(
                session,
                user_id,
                companion_id,
                decision_id,
                message_id=message_id,
                content=content,
            )
        else:
            async with session.begin():
                decision = await self._complete_sent_message(
                    session,
                    user_id,
                    companion_id,
                    decision_id,
                    message_id=message_id,
                    content=content,
                )
        logger.info("completed decision %s as message %s", decision.id, decision.result_message_id)
        return decision

    async def _complete_sent_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        *,
        message_id: uuid.UUID,
        content: str,
    ) -> DialogueDecision:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        decision = await self._decisions.get_for_update(session, decision_id, companion_id)
        if decision is None:
            raise NotFoundError("决策不存在")
        if decision.status != DecisionStatus.APPROVED.value or decision.conversation_id is None:
            raise ConflictError("决策当前不能生成消息")
        message = await self._conversations.record_turn_message(
            session,
            user_id,
            companion_id,
            decision.conversation_id,
            message_id=message_id,
            content=content,
            status=MessageStatus.COMPLETED,
        )
        decision.result_message_id = message.id
        decision.status = DecisionStatus.COMPLETED.value
        decision.completed_at = datetime.now(UTC)
        return decision

    async def close_unfinished(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        *,
        final_status: DecisionStatus,
        message_id: uuid.UUID | None = None,
        content: str | None = None,
    ) -> None:
        if final_status not in {DecisionStatus.FAILED, DecisionStatus.CANCELLED}:
            raise AppError("未完成的决策只能失败或取消")
        if session.in_transaction():
            await self._close_unfinished(
                session,
                user_id,
                companion_id,
                decision_id,
                final_status=final_status,
                message_id=message_id,
                content=content,
            )
        else:
            async with session.begin():
                await self._close_unfinished(
                    session,
                    user_id,
                    companion_id,
                    decision_id,
                    final_status=final_status,
                    message_id=message_id,
                    content=content,
                )
        logger.info("closed unfinished decision %s as %s", decision_id, final_status.value)

    async def _close_unfinished(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        *,
        final_status: DecisionStatus,
        message_id: uuid.UUID | None = None,
        content: str | None = None,
    ) -> None:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        decision = await self._decisions.get_for_update(session, decision_id, companion_id)
        if decision is None or decision.status != DecisionStatus.APPROVED.value:
            return
        text = content.strip() if content else ""
        if text and message_id is not None and decision.conversation_id is not None:
            message_status = (
                MessageStatus.INTERRUPTED if final_status == DecisionStatus.CANCELLED else MessageStatus.FAILED
            )
            message = await self._conversations.record_turn_message(
                session,
                user_id,
                companion_id,
                decision.conversation_id,
                message_id=message_id,
                content=text,
                status=message_status,
            )
            decision.result_message_id = message.id
        decision.status = final_status.value
        decision.completed_at = None

    async def find_by_trigger_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> DialogueDecision | None:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._decisions.find_by_trigger_message(session, companion_id, message_id)

    async def suppress_unsent(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        reason: str,
    ) -> DialogueDecision:
        if session.in_transaction():
            decision = await self._suppress_unsent(session, user_id, companion_id, decision_id, reason)
        else:
            async with session.begin():
                decision = await self._suppress_unsent(session, user_id, companion_id, decision_id, reason)
        logger.info("suppressed unsent decision %s", decision.id)
        return decision

    async def _suppress_unsent(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        decision_id: uuid.UUID,
        reason: str,
    ) -> DialogueDecision:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        decision = await self._decisions.get_for_update(session, decision_id, companion_id)
        if decision is None:
            raise NotFoundError("决策不存在")
        if decision.status != DecisionStatus.APPROVED.value or decision.result_message_id is not None:
            raise ConflictError("决策已经完成")
        now = datetime.now(UTC)
        decision.primary_action = DialogueAction.QUIET.value
        decision.secondary_actions = []
        decision.status = DecisionStatus.COMPLETED.value
        decision.completed_at = now
        decision.validation_result = {
            **decision.validation_result,
            "should_send": False,
            "suppressed": reason,
        }
        return decision

    async def save_validated_decision(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        *,
        trigger_type: TriggerType,
        conversation_id: uuid.UUID | None,
        trigger_message_id: uuid.UUID | None,
        primary_action: DialogueAction,
        secondary_actions: list[DialogueAction],
        motivation: DecisionMotivation,
        topic: DecisionTopic,
        confidence: Decimal,
        reasoning_summary: str,
        model_proposal: dict[str, object],
        validation_result: dict[str, object],
        should_send: bool,
        decision_id: uuid.UUID | None = None,
    ) -> DialogueDecision:
        if session.in_transaction():
            decision = await self._save_validated_decision(
                session,
                user_id,
                companion_id,
                trigger_type=trigger_type,
                conversation_id=conversation_id,
                trigger_message_id=trigger_message_id,
                primary_action=primary_action,
                secondary_actions=secondary_actions,
                motivation=motivation,
                topic=topic,
                confidence=confidence,
                reasoning_summary=reasoning_summary,
                model_proposal=model_proposal,
                validation_result=validation_result,
                should_send=should_send,
                decision_id=decision_id,
            )
        else:
            async with session.begin():
                decision = await self._save_validated_decision(
                    session,
                    user_id,
                    companion_id,
                    trigger_type=trigger_type,
                    conversation_id=conversation_id,
                    trigger_message_id=trigger_message_id,
                    primary_action=primary_action,
                    secondary_actions=secondary_actions,
                    motivation=motivation,
                    topic=topic,
                    confidence=confidence,
                    reasoning_summary=reasoning_summary,
                    model_proposal=model_proposal,
                    validation_result=validation_result,
                    should_send=should_send,
                    decision_id=decision_id,
                )
        logger.info("saved validated decision %s action %s", decision.id, decision.primary_action)
        return decision

    async def _save_validated_decision(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        *,
        trigger_type: TriggerType,
        conversation_id: uuid.UUID | None,
        trigger_message_id: uuid.UUID | None,
        primary_action: DialogueAction,
        secondary_actions: list[DialogueAction],
        motivation: DecisionMotivation,
        topic: DecisionTopic,
        confidence: Decimal,
        reasoning_summary: str,
        model_proposal: dict[str, object],
        validation_result: dict[str, object],
        should_send: bool,
        decision_id: uuid.UUID | None = None,
    ) -> DialogueDecision:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        state = await self._states.get_current(session, user_id, companion_id)
        if trigger_type == TriggerType.PROACTIVE and should_send:
            self._require_proactive_permission(
                RecordDecisionRequest(
                    trigger_type=trigger_type,
                    conversation_id=conversation_id,
                    primary_action=primary_action,
                    secondary_actions=secondary_actions,
                    motivation=motivation,
                    topic=topic,
                    confidence=confidence,
                    reasoning_summary=reasoning_summary,
                ),
                state.interaction,
            )
        if should_send and conversation_id is None:
            raise AppError("发送决策必须关联会话")
        if trigger_message_id is not None:
            message = await self._conversations.get_owned_message(
                session,
                user_id,
                companion_id,
                trigger_message_id,
            )
            if conversation_id is not None and message.conversation_id != conversation_id:
                raise AppError("消息不属于该会话")
        now = datetime.now(UTC)
        quiet = primary_action == DialogueAction.QUIET or not should_send
        decision = DialogueDecision(
            id=decision_id if decision_id is not None else uuid.uuid4(),
            companion_id=companion_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            result_message_id=None,
            trigger_type=trigger_type.value,
            primary_action=DialogueAction.QUIET.value if quiet else primary_action.value,
            secondary_actions=[] if quiet else [item.value for item in secondary_actions],
            motivation=motivation.model_dump(mode="json"),
            topic=topic.model_dump(mode="json"),
            model_proposal=model_proposal,
            validation_result={**validation_result, "should_send": not quiet},
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            status=DecisionStatus.COMPLETED.value if quiet else DecisionStatus.APPROVED.value,
            created_at=now,
            completed_at=now if quiet else None,
        )
        await self._decisions.add(session, decision)
        return decision

    async def _require(
        self,
        session: AsyncSession,
        decision_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> DialogueDecision:
        decision = await self._decisions.get_for_companion(session, decision_id, companion_id)
        if decision is None:
            raise NotFoundError("决策不存在")
        return decision

    async def _resolve_conversation(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        data: RecordDecisionRequest,
    ) -> uuid.UUID | None:
        message = None
        if data.trigger_message_id is not None:
            message = await self._conversations.get_owned_message(
                session,
                user_id,
                companion_id,
                data.trigger_message_id,
            )
        if data.conversation_id is not None:
            conversation = await self._conversations.get_owned_conversation(
                session,
                user_id,
                companion_id,
                data.conversation_id,
            )
            if message is not None and message.conversation_id != conversation.id:
                raise AppError("消息不属于该会话")
            return conversation.id
        if message is not None:
            return message.conversation_id
        return None

    def _require_send_target(self, data: RecordDecisionRequest, conversation_id: uuid.UUID | None) -> None:
        if data.primary_action != DialogueAction.QUIET and conversation_id is None:
            raise AppError("发送决策必须关联会话")

    def _require_proactive_permission(self, data: RecordDecisionRequest, interaction: dict[str, object]) -> None:
        if data.trigger_type != TriggerType.PROACTIVE:
            return
        current = InteractionState.model_validate(interaction)
        if not current.proactive_allowed or current.mode not in _PROACTIVE_MODES:
            raise AppError("当前不允许主动交流")


def to_decision_response(decision: DialogueDecision) -> DecisionResponse:
    return DecisionResponse(
        id=decision.id,
        companion_id=decision.companion_id,
        conversation_id=decision.conversation_id,
        trigger_message_id=decision.trigger_message_id,
        result_message_id=decision.result_message_id,
        trigger_type=TriggerType(decision.trigger_type),
        primary_action=DialogueAction(decision.primary_action),
        secondary_actions=[DialogueAction(item) for item in decision.secondary_actions],
        motivation=decision.motivation,
        topic=decision.topic,
        confidence=decision.confidence,
        reasoning_summary=decision.reasoning_summary,
        status=DecisionStatus(decision.status),
        created_at=decision.created_at,
        completed_at=decision.completed_at,
    )
