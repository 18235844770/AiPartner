import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.dialogue.services.dialogue_service import DialogueService
from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import ModelCallLogResponse, RecordModelCallRequest
from app.modules.infrastructure.domain.enums import ModelCallStatus, ModelProvider, ModelTaskType
from app.modules.infrastructure.repositories.infrastructure_repository import (
    BackgroundTaskRepository,
    ModelCallLogRepository,
    ModelConfigRepository,
)
from app.modules.infrastructure.repositories.models import ModelCallLog
from app.shared.exceptions.errors import AppError, NotFoundError

logger = logging.getLogger(__name__)


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

    async def record(self, session: AsyncSession, data: RecordModelCallRequest) -> ModelCallLog:
        async with session.begin():
            await self._check_scope(session, data)
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
                created_at=data.created_at,
                completed_at=data.completed_at,
            )
            await self._logs.add(session, log)
        logger.info("recorded model call %s status %s", log.id, log.status)
        return log

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
