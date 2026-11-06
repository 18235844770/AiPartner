import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import (
    BackgroundTaskResponse,
    CreateBackgroundTaskRequest,
    TaskTransitionRequest,
)
from app.modules.infrastructure.domain.enums import BackgroundTaskStatus, BackgroundTaskType
from app.modules.infrastructure.repositories.infrastructure_repository import BackgroundTaskRepository
from app.modules.infrastructure.repositories.models import BackgroundTask
from app.shared.exceptions.errors import AppError, ConflictError, NotFoundError

logger = logging.getLogger(__name__)

RECENT_TASK_LIMIT = 50


class TaskWriteResult:
    def __init__(self, task: BackgroundTask, created: bool) -> None:
        self.task = task
        self.created = created


class BackgroundTaskService:
    def __init__(
        self,
        tasks: BackgroundTaskRepository | None = None,
        identity: IdentityService | None = None,
    ) -> None:
        self._tasks = tasks or BackgroundTaskRepository()
        self._identity = identity or IdentityService()

    async def create(self, session: AsyncSession, data: CreateBackgroundTaskRequest) -> TaskWriteResult:
        if session.in_transaction():
            result = await self._create(session, data)
        else:
            async with session.begin():
                result = await self._create(session, data)
        if result.created:
            logger.info("created background task %s", result.task.id)
        return result

    async def _create(self, session: AsyncSession, data: CreateBackgroundTaskRequest) -> TaskWriteResult:
        if data.companion_id is not None and data.user_id is not None:
            await self._identity.get_owned_companion(session, data.user_id, data.companion_id)
        existing = await self._tasks.lock_by_key(session, data.task_key)
        if existing is not None:
            self._require_same_task(existing, data)
            return TaskWriteResult(existing, created=False)
        now = datetime.now(UTC)
        task = BackgroundTask(
            companion_id=data.companion_id,
            task_type=data.task_type.value,
            task_key=data.task_key,
            queue_name=data.queue_name,
            status=BackgroundTaskStatus.PENDING.value,
            payload=data.payload,
            result=None,
            error_message=None,
            retry_count=0,
            max_retries=data.max_retries,
            scheduled_at=data.scheduled_at,
            dispatched_at=None,
            locked_at=None,
            worker_id=None,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        await self._tasks.add(session, task)
        return TaskWriteResult(task, created=True)

    async def list_for_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[BackgroundTask]:
        if session.in_transaction():
            return await self._list_for_companion(session, user_id, companion_id)
        async with session.begin():
            return await self._list_for_companion(session, user_id, companion_id)

    async def _list_for_companion(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[BackgroundTask]:
        await self._identity.get_owned_companion(session, user_id, companion_id)
        return await self._tasks.list_recent_by_companion(session, companion_id, RECENT_TASK_LIMIT)

    async def get(self, session: AsyncSession, task_id: uuid.UUID) -> BackgroundTask:
        if session.in_transaction():
            return await self._require(session, task_id)
        async with session.begin():
            return await self._require(session, task_id)

    async def transition(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        data: TaskTransitionRequest,
    ) -> BackgroundTask:
        async with session.begin():
            task = await self._tasks.lock(session, task_id)
            if task is None:
                raise NotFoundError("任务不存在")
            self._apply(task, data, datetime.now(UTC))
        logger.info("background task %s moved to %s", task.id, task.status)
        return task

    def apply_locked(self, task: BackgroundTask, data: TaskTransitionRequest, now: datetime) -> None:
        self._apply(task, data, now)

    async def _require(self, session: AsyncSession, task_id: uuid.UUID) -> BackgroundTask:
        task = await self._tasks.get(session, task_id)
        if task is None:
            raise NotFoundError("任务不存在")
        return task

    def _require_same_task(self, existing: BackgroundTask, data: CreateBackgroundTaskRequest) -> None:
        same = (
            existing.task_type == data.task_type.value
            and existing.companion_id == data.companion_id
            and existing.queue_name == data.queue_name
            and existing.max_retries == data.max_retries
            and _canonical(existing.payload) == _canonical(data.payload)
        )
        if not same:
            raise ConflictError("任务标识已被使用")

    def _apply(self, task: BackgroundTask, data: TaskTransitionRequest, now: datetime) -> None:
        current = BackgroundTaskStatus(task.status)
        target = data.status
        if current == BackgroundTaskStatus.PENDING and target == BackgroundTaskStatus.QUEUED:
            task.status = BackgroundTaskStatus.QUEUED.value
            task.dispatched_at = now
        elif current == BackgroundTaskStatus.RETRYING and target == BackgroundTaskStatus.QUEUED:
            task.status = BackgroundTaskStatus.QUEUED.value
            task.dispatched_at = now
        elif current == BackgroundTaskStatus.QUEUED and target == BackgroundTaskStatus.RUNNING:
            if data.worker_id is None:
                raise AppError("运行任务必须提供 worker")
            task.status = BackgroundTaskStatus.RUNNING.value
            task.worker_id = data.worker_id
            task.started_at = now
            task.locked_at = now
        elif current == BackgroundTaskStatus.RUNNING and target == BackgroundTaskStatus.COMPLETED:
            task.status = BackgroundTaskStatus.COMPLETED.value
            task.result = data.result or {}
            task.completed_at = now
            task.locked_at = None
        elif current == BackgroundTaskStatus.RUNNING and target == BackgroundTaskStatus.FAILED:
            if data.error_message is None:
                raise AppError("失败任务必须记录错误")
            task.retry_count += 1
            task.error_message = data.error_message
            task.locked_at = None
            task.worker_id = None
            task.started_at = None
            if task.retry_count <= task.max_retries:
                task.status = BackgroundTaskStatus.RETRYING.value
                task.dispatched_at = None
            else:
                task.status = BackgroundTaskStatus.FAILED.value
                task.completed_at = now
        elif current in {
            BackgroundTaskStatus.PENDING,
            BackgroundTaskStatus.QUEUED,
            BackgroundTaskStatus.RETRYING,
        } and target == BackgroundTaskStatus.CANCELLED:
            task.status = BackgroundTaskStatus.CANCELLED.value
            task.completed_at = now
            task.locked_at = None
            task.dispatched_at = task.dispatched_at if current != BackgroundTaskStatus.PENDING else None
        else:
            raise AppError("任务状态不能这样变更")
        task.updated_at = now


def to_task_response(task: BackgroundTask) -> BackgroundTaskResponse:
    return BackgroundTaskResponse(
        id=task.id,
        companion_id=task.companion_id,
        task_type=BackgroundTaskType(task.task_type),
        task_key=task.task_key,
        queue_name=task.queue_name,
        status=BackgroundTaskStatus(task.status),
        payload=task.payload,
        result=task.result,
        error_message=task.error_message,
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        scheduled_at=task.scheduled_at,
        dispatched_at=task.dispatched_at,
        locked_at=task.locked_at,
        worker_id=task.worker_id,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
