import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
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
    """用会话级咨询锁保证同一任务不会并发执行。运行状态先提交，处理器再写模型日志。"""

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
        engine = self._session_factory.kw["bind"]
        async with engine.connect() as connection:
            hi, lo = _advisory_keys(task_id)
            await connection.execute(text("SELECT pg_advisory_lock(:hi, :lo)"), {"hi": hi, "lo": lo})
            await connection.commit()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                return await self._execute_locked(session, task_id, worker_id, handlers)
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:hi, :lo)"), {"hi": hi, "lo": lo})
                await connection.commit()
                await session.close()

    async def _execute_locked(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        worker_id: str,
        handlers: Mapping[str, TaskHandler],
    ) -> BackgroundTask | None:
        async with session.begin():
            task = await self._tasks.lock(session, task_id)
            if task is None:
                logger.warning("background task %s is missing", task_id)
                return None
            if task.status in _TERMINAL or task.status == BackgroundTaskStatus.RUNNING.value:
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
            async with session.begin():
                task = await self._tasks.get(session, task_id)
                if task is None or task.status != BackgroundTaskStatus.RUNNING.value or task.worker_id != worker_id:
                    return task
                result = _result_payload(await handler(session, task))
                locked = await self._tasks.lock(session, task_id)
                if locked is None or locked.status != BackgroundTaskStatus.RUNNING.value or locked.worker_id != worker_id:
                    return locked
                self._records.apply_locked(
                    locked,
                    TaskTransitionRequest(status=BackgroundTaskStatus.COMPLETED, result=result),
                    datetime.now(UTC),
                )
                task = locked
        except Exception as exc:
            logger.warning("background task %s failed: %s", task_id, type(exc).__name__)
            async with session.begin():
                task = await self._tasks.lock(session, task_id)
                if task is None or task.status != BackgroundTaskStatus.RUNNING.value or task.worker_id != worker_id:
                    return task
                self._fail(task, str(exc))
        logger.info("finished background task %s as %s", task_id, None if task is None else task.status)
        return task

    def _fail(self, task: BackgroundTask, message: str) -> None:
        cleaned = message.strip()[:500] or "任务执行失败"
        self._records.apply_locked(
            task,
            TaskTransitionRequest(status=BackgroundTaskStatus.FAILED, error_message=cleaned),
            datetime.now(UTC),
        )


def _advisory_keys(task_id: uuid.UUID) -> tuple[int, int]:
    raw = task_id.bytes
    return int.from_bytes(raw[:4], "big", signed=True), int.from_bytes(raw[4:8], "big", signed=True)


def _result_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("任务结果必须是对象")
    reject_secret_keys(value)
    return value
