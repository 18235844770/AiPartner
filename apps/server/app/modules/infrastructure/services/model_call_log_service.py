import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.services.dialogue_service import DialogueService
from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import (
    ModelCallLogResponse,
    ModelCallSnapshotResponse,
    RecordModelCallRequest,
)
from app.config.settings import get_settings
from app.modules.infrastructure.domain.enums import ModelCallStatus, ModelProvider, ModelTaskType
from app.modules.infrastructure.domain.log_capture import log_policy, omit_text, redact_secrets
from app.modules.infrastructure.repositories.infrastructure_repository import (
    BackgroundTaskRepository,
    ModelCallLogRepository,
    ModelConfigRepository,
)
from app.modules.infrastructure.repositories.models import ModelCallLog
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import AppError, NotFoundError

logger = logging.getLogger(__name__)

RECENT_CALL_LIMIT = 50


class CallDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    returned_model_name: str | None = None
    parameters: dict[str, object] | None = None
    prompt_snapshot: str | None = None
    messages_snapshot: list[dict[str, object]] | None = None
    response_snapshot: dict[str, object] | None = None
    context_versions: dict[str, object] | None = None


class ModelCallLogService:
    def __init__(
        self,
        logs: ModelCallLogRepository | None = None,
        configs: ModelConfigRepository | None = None,
        tasks: BackgroundTaskRepository | None = None,
        identity: IdentityService | None = None,
        conversations: ConversationService | None = None,
        dialogue: DialogueService | None = None,
    ) -> None:
        self._logs = logs or ModelCallLogRepository()
        self._configs = configs or ModelConfigRepository()
        self._tasks = tasks or BackgroundTaskRepository()
        self._identity = identity or IdentityService()
        self._conversations = conversations or ConversationService()
        self._dialogue = dialogue or DialogueService()

    async def record(
        self,
        session: AsyncSession,
        data: RecordModelCallRequest,
        detail: CallDetail | None = None,
    ) -> ModelCallLog:
        async with session.begin():
            await self._logs.expire_details(session, datetime.now(UTC))
            await self._check_scope(session, data)
            stored = _stored_detail(detail)
            log = ModelCallLog(
                companion_id=data.companion_id,
                conversation_id=data.conversation_id,
                dialogue_decision_id=data.dialogue_decision_id,
                background_task_id=data.background_task_id,
                config_id=data.config_id,
                trace_id=data.trace_id,
                task_type=data.task_type.value,
                provider=data.provider.value,
                model_name=data.model_name,
                status=data.status.value,
                latency_ms=data.latency_ms,
                input_tokens=data.input_tokens,
                output_tokens=data.output_tokens,
                error_code=data.error_code,
                error_message=data.error_message,
                returned_model_name=None if stored is None else stored.returned_model_name,
                parameters=None if stored is None else stored.parameters,
                prompt_snapshot=None if stored is None else stored.prompt_snapshot,
                messages_snapshot=None if stored is None else stored.messages_snapshot,
                response_snapshot=None if stored is None else stored.response_snapshot,
                context_versions=None if stored is None else stored.context_versions,
                detail_retained_until=None if stored is None else _retention_deadline(),
                created_at=data.created_at,
                completed_at=data.completed_at,
            )
            await self._logs.add(session, log)
        logger.info("recorded model call %s status %s", log.id, log.status)
        return log

    async def attach_decision(self, trace_id: uuid.UUID, decision_id: uuid.UUID) -> None:
        async with get_session_factory()() as session:
            async with session.begin():
                await self._logs.attach_decision(session, trace_id, decision_id)

    async def get_snapshot(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        log_id: uuid.UUID,
    ) -> ModelCallLog:
        if not log_policy(get_settings()).expose_snapshots:
            raise NotFoundError("调用快照不可用")
        if session.in_transaction():
            return await self._get_snapshot(session, user_id, companion_id, log_id)
        async with session.begin():
            return await self._get_snapshot(session, user_id, companion_id, log_id)

    async def _get_snapshot(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        log_id: uuid.UUID,
    ) -> ModelCallLog:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        log = await self._logs.get(session, log_id)
        if log is None or log.companion_id != companion_id:
            raise NotFoundError("调用不存在")
        if log.messages_snapshot is None and log.prompt_snapshot is None and log.response_snapshot is None:
            raise NotFoundError("调用快照不可用")
        return log

    async def list_for_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[ModelCallLog]:
        if session.in_transaction():
            return await self._list_for_companion(session, user_id, companion_id)
        async with session.begin():
            return await self._list_for_companion(session, user_id, companion_id)

    async def _list_for_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[ModelCallLog]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        return await self._logs.list_recent_by_companion(session, companion_id, RECENT_CALL_LIMIT)

    async def list_by_trace(self, session: AsyncSession, trace_id: uuid.UUID) -> list[ModelCallLog]:
        async with session.begin():
            return await self._logs.list_by_trace(session, trace_id)

    async def _check_scope(self, session: AsyncSession, data: RecordModelCallRequest) -> None:
        if data.user_id is not None and data.companion_id is not None:
            await self._identity.get_owned_companion(session, data.user_id, data.companion_id)
        if data.conversation_id is not None and data.user_id is not None and data.companion_id is not None:
            await self._conversations.get_owned_conversation(
                session,
                data.user_id,
                data.companion_id,
                data.conversation_id,
            )
        if data.dialogue_decision_id is not None and data.user_id is not None and data.companion_id is not None:
            decision = await self._dialogue.get_decision(
                session,
                data.user_id,
                data.companion_id,
                data.dialogue_decision_id,
            )
            if data.conversation_id is not None and decision.conversation_id not in {None, data.conversation_id}:
                raise AppError("决策不属于该会话")
        if data.config_id is not None:
            config = await self._configs.get(session, data.config_id)
            if config is None:
                raise NotFoundError("配置不存在")
            if config.task_type != data.task_type.value:
                raise AppError("配置与任务不一致")
        if data.background_task_id is not None:
            task = await self._tasks.get(session, data.background_task_id)
            if task is None:
                raise NotFoundError("任务不存在")
            if task.companion_id != data.companion_id:
                raise AppError("任务不属于该陪伴者")


def to_log_response(log: ModelCallLog) -> ModelCallLogResponse:
    return ModelCallLogResponse(
        id=log.id,
        companion_id=log.companion_id,
        conversation_id=log.conversation_id,
        dialogue_decision_id=log.dialogue_decision_id,
        background_task_id=log.background_task_id,
        config_id=log.config_id,
        trace_id=log.trace_id,
        task_type=ModelTaskType(log.task_type),
        provider=ModelProvider(log.provider),
        model_name=log.model_name,
        status=ModelCallStatus(log.status),
        latency_ms=log.latency_ms,
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        error_code=log.error_code,
        error_message=log.error_message,
        created_at=log.created_at,
        completed_at=log.completed_at,
    )


def to_snapshot_response(log: ModelCallLog) -> ModelCallSnapshotResponse:
    messages = log.messages_snapshot if isinstance(log.messages_snapshot, list) else None
    response = log.response_snapshot if isinstance(log.response_snapshot, dict) else None
    parameters = log.parameters if isinstance(log.parameters, dict) else None
    versions = log.context_versions if isinstance(log.context_versions, dict) else None
    return ModelCallSnapshotResponse(
        id=log.id,
        trace_id=log.trace_id,
        task_type=ModelTaskType(log.task_type),
        model_name=log.model_name,
        returned_model_name=log.returned_model_name,
        parameters=parameters,
        prompt_snapshot=log.prompt_snapshot,
        messages_snapshot=messages,
        response_snapshot=response,
        context_versions=versions,
        input_tokens=log.input_tokens,
        output_tokens=log.output_tokens,
        detail_retained_until=log.detail_retained_until,
    )


def _stored_detail(detail: CallDetail | None) -> CallDetail | None:
    if detail is None:
        return None
    policy = log_policy(get_settings())
    if policy.detail == "off" or random.random() > policy.sample_rate:
        return None
    payload = redact_secrets(detail.model_dump(mode="json"))
    if not isinstance(payload, dict):
        return None
    if policy.detail == "redacted":
        prompt = payload.get("prompt_snapshot")
        if isinstance(prompt, str):
            payload["prompt_snapshot"] = f"[omitted:{len(prompt)}]"
        payload = omit_text(payload)
        if not isinstance(payload, dict):
            return None
    return CallDetail.model_validate(payload)


def _retention_deadline() -> datetime:
    days = log_policy(get_settings()).retention_days
    return datetime.now(UTC) + timedelta(days=days)
