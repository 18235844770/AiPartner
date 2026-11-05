import logging
import uuid
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.infrastructure.api.schemas import TaskTransitionRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskStatus
from app.modules.infrastructure.repositories.infrastructure_repository import BackgroundTaskRepository
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_queue import TaskQueue
from app.shared.database.session import get_session_factory

logger = logging.getLogger(__name__)

DISPATCH_LIMIT = 20
_DELIVERABLE = {BackgroundTaskStatus.PENDING.value, BackgroundTaskStatus.RETRYING.value}


class TaskDispatcher:
    """扫描 PostgreSQL 里待投递的任务。Redis 失败时保留原状态，下次再投。"""

    def __init__(
        self,
        tasks: BackgroundTaskRepository | None = None,
        records: BackgroundTaskService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._tasks = tasks or BackgroundTaskRepository()
        self._records = records or BackgroundTaskService()
        self._session_factory = session_factory or get_session_factory()

    async def dispatch_due(self, queue: TaskQueue, *, now: datetime | None = None, limit: int = DISPATCH_LIMIT) -> int:
        moment = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                task_ids = await self._tasks.list_due_ids(session, moment, limit)
        delivered = 0
        for task_id in task_ids:
            if await self.dispatch_task(queue, task_id, now=moment):
                delivered += 1
        return delivered

    async def dispatch_task(self, queue: TaskQueue, task_id: uuid.UUID, *, now: datetime | None = None) -> bool:
        return await self._deliver(queue, task_id, now or datetime.now(UTC))

    async def _deliver(self, queue: TaskQueue, task_id: uuid.UUID, now: datetime) -> bool:
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    task = await self._tasks.lock(session, task_id)
                    if task is None or task.dispatched_at is not None or task.status not in _DELIVERABLE:
                        return False
                    if task.scheduled_at > now:
                        return False
                    await queue.enqueue(task.id, task.retry_count)
                    self._records.apply_locked(
                        task,
                        TaskTransitionRequest(status=BackgroundTaskStatus.QUEUED),
                        now,
                    )
            except (OSError, RedisError, TimeoutError):
                logger.warning("background task %s was not dispatched", task_id)
                return False
        logger.info("dispatched background task %s", task_id)
        return True
