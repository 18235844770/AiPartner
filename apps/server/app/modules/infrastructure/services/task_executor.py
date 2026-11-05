import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.infrastructure.api.schemas import TaskTransitionRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskStatus
from app.modules.infrastructure.domain.secrets import reject_secret_keys
from app.modules.infrastructure.repositories.infrastructure_repository import BackgroundTaskRepository
from app.modules.infrastructure.repositories.models import BackgroundTask
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.shared.database.session import get_session_factory

logger = logging.getLogger(__name__)

_TERMINAL = {
    BackgroundTaskStatus.COMPLETED.value,
    BackgroundTaskStatus.FAILED.value,
    BackgroundTaskStatus.CANCELLED.value,
}
_MISSING_HANDLER = "任务执行器尚未实现"


class TaskHandler(Protocol):
    async def __call__(self, session: AsyncSession, task: BackgroundTask) -> dict[str, object]: ...


class TaskExecutor:
    """同一次任务持有行锁直到结束。后到的投递会看到已经完成的结果，不再执行。"""

    def __init__(
        self,
        tasks: BackgroundTaskRepository | None = None,
        records: BackgroundTaskService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._tasks = tasks or BackgroundTaskRepository()
        self._records = records or BackgroundTaskService()
        self._session_factory = session_factory or get_session_factory()

    async def execute(
        self,
        task_id: uuid.UUID,
        worker_id: str,
        handlers: Mapping[str, TaskHandler],
    ) -> BackgroundTask | None:
        async with self._session_factory() as session:
            async with session.begin():
                task = await self._tasks.lock(session, task_id)
                if task is None:
                    logger.warning("background task %s is missing", task_id)
                    return None
                if task.status in _TERMINAL:
                    return task
                now = datetime.now(UTC)
                if task.status in {BackgroundTaskStatus.PENDING.value, BackgroundTaskStatus.RETRYING.value}:
                    self._records.apply_locked(task, TaskTransitionRequest(status=BackgroundTaskStatus.QUEUED), now)
                if task.status == BackgroundTaskStatus.QUEUED.value:
                    self._records.apply_locked(
                        task,
                        TaskTransitionRequest(status=BackgroundTaskStatus.RUNNING, worker_id=worker_id),
                        now,
                    )
                if task.status != BackgroundTaskStatus.RUNNING.value:
                    return task
                handler = handlers.get(task.task_type)
                if handler is None:
                    self._fail(task, _MISSING_HANDLER)
                    return task
                try:
                    async with session.begin_nested():
                        result = _result_payload(await handler(session, task))
                except Exception as exc:
                    logger.warning("background task %s failed: %s", task.id, type(exc).__name__)
                    self._fail(task, str(exc))
                    return task
                self._records.apply_locked(
                    task,
                    TaskTransitionRequest(status=BackgroundTaskStatus.COMPLETED, result=result),
                    datetime.now(UTC),
                )
        logger.info("finished background task %s as %s", task.id, task.status)
        return task

    def _fail(self, task: BackgroundTask, message: str) -> None:
        cleaned = message.strip()[:500] or "任务执行失败"
        self._records.apply_locked(
            task,
            TaskTransitionRequest(status=BackgroundTaskStatus.FAILED, error_message=cleaned),
            datetime.now(UTC),
        )


def _result_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("任务结果必须是对象")
    reject_secret_keys(value)
    return value
