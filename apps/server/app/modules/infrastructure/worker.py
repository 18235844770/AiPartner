import logging
import os
import socket
import uuid
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from app.config.settings import get_settings
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.task_dispatcher import TaskDispatcher
from app.modules.infrastructure.services.task_executor import TaskHandler, TaskExecutor
from app.modules.infrastructure.services.task_queue import JOB_NAME, ArqTaskQueue
from app.modules.memory.services.embedding import MemoryEmbeddingService
from app.modules.memory.services.evaluation import MemoryEvaluationService
from app.modules.memory.services.extraction import MemoryExtractionService
from app.modules.memory.services.relation import MemoryRelationService
from app.modules.memory.services.summary import MemorySummaryService
from app.modules.state.services.maintenance import StateMaintenanceService
from app.modules.dialogue.services.proactive import ProactiveCheckService

logger = logging.getLogger(__name__)

async def extract_memory_task(session: Any, task: Any) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("记忆提取任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        message_id = uuid.UUID(str(payload["message_id"]))
        conversation_id = uuid.UUID(str(payload["conversation_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("记忆提取任务参数不正确") from exc
    return await MemoryExtractionService().extract(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_id=task.id,
    )


async def evaluate_memory_task(session: Any, task: Any) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("记忆评分任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        message_id = uuid.UUID(str(payload["message_id"]))
        conversation_id = uuid.UUID(str(payload["conversation_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("记忆评分任务参数不正确") from exc
    return await MemoryEvaluationService().evaluate(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_id=task.id,
    )


async def embed_memory_task(
    session: Any,
    task: Any,
    service: MemoryEmbeddingService | None = None,
) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("记忆向量任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        memory_id = uuid.UUID(str(payload["memory_id"]))
        version_id = uuid.UUID(str(payload["version_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("记忆向量任务参数不正确") from exc
    return await (service or MemoryEmbeddingService()).embed_version(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
        memory_id=memory_id,
        version_id=version_id,
        task_id=task.id,
    )


async def relate_memory_task(session: Any, task: Any) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("记忆关联任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        message_id = uuid.UUID(str(payload["message_id"]))
        conversation_id = uuid.UUID(str(payload["conversation_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("记忆关联任务参数不正确") from exc
    return await MemoryRelationService().relate(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_id=task.id,
    )


async def summarize_memory_task(session: Any, task: Any) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("工作记忆摘要任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        message_id = uuid.UUID(str(payload["message_id"]))
        conversation_id = uuid.UUID(str(payload["conversation_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("工作记忆摘要任务参数不正确") from exc
    return await MemorySummaryService().summarize(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
        conversation_id=conversation_id,
        message_id=message_id,
        task_id=task.id,
    )


async def maintain_state_task(session: Any, task: Any) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("状态维护任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
        message_id = _optional_uuid(payload.get("message_id"))
        conversation_id = _optional_uuid(payload.get("conversation_id"))
    except (KeyError, ValueError) as exc:
        raise ValueError("状态维护任务参数不正确") from exc
    return await StateMaintenanceService().maintain(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )


async def check_proactive_task(session: Any, task: Any) -> dict[str, object]:
    payload = task.payload
    if task.companion_id is None or not isinstance(payload, dict):
        raise ValueError("主动检查任务参数不正确")
    try:
        user_id = uuid.UUID(str(payload["user_id"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("主动检查任务参数不正确") from exc
    return await ProactiveCheckService().check(
        session,
        user_id=user_id,
        companion_id=task.companion_id,
    )


def _optional_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    return uuid.UUID(str(value))


HANDLERS: dict[str, TaskHandler] = {
    BackgroundTaskType.MEMORY_EXTRACT.value: extract_memory_task,
    BackgroundTaskType.MEMORY_EVALUATE.value: evaluate_memory_task,
    BackgroundTaskType.MEMORY_EMBEDDING.value: embed_memory_task,
    BackgroundTaskType.MEMORY_RELATION.value: relate_memory_task,
    BackgroundTaskType.MEMORY_SUMMARIZE.value: summarize_memory_task,
    BackgroundTaskType.STATE_MAINTENANCE.value: maintain_state_task,
    BackgroundTaskType.PROACTIVE_CHECK.value: check_proactive_task,
}


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:128]


async def execute_background_task(ctx: dict[Any, Any], task_id: str) -> None:
    del ctx
    await TaskExecutor().execute(uuid.UUID(task_id), worker_identity(), HANDLERS)


async def dispatch_outbox(ctx: dict[Any, Any]) -> None:
    delivered = await TaskDispatcher().dispatch_due(ArqTaskQueue(ctx["redis"]))
    logger.info("dispatched %s background tasks", delivered)


async def schedule_state_maintenance(ctx: dict[Any, Any]) -> None:
    del ctx
    created = await StateMaintenanceService().schedule_due()
    logger.info("scheduled %s state maintenance tasks", created)


async def schedule_proactive_checks(ctx: dict[Any, Any]) -> None:
    del ctx
    created = await ProactiveCheckService().schedule_due()
    logger.info("scheduled %s proactive checks", created)


class WorkerSettings:
    functions = [func(execute_background_task, name=JOB_NAME, max_tries=5)]
    cron_jobs = [
        cron(dispatch_outbox, second={0, 15, 30, 45}, run_at_startup=True, max_tries=1),
        cron(schedule_state_maintenance, minute={0, 15, 30, 45}, run_at_startup=True, max_tries=1),
        cron(schedule_proactive_checks, minute={5, 20, 35, 50}, run_at_startup=True, max_tries=1),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 10
    job_timeout = 300
