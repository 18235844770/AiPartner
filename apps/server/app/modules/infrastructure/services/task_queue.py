import logging
import uuid
from typing import Any, Protocol

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

JOB_NAME = "execute_background_task"


class TaskQueue(Protocol):
    async def enqueue(self, task_id: uuid.UUID, attempt: int) -> None:
        """把这一次尝试放进队列。同一次尝试已经存在时直接返回。连接失败时抛出异常。"""


class SupportsEnqueue(Protocol):
    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> object: ...


class ArqTaskQueue:
    def __init__(self, redis: SupportsEnqueue) -> None:
        self._redis = redis

    async def enqueue(self, task_id: uuid.UUID, attempt: int) -> None:
        job_id = f"{task_id}:{attempt}"
        try:
            await self._redis.enqueue_job(JOB_NAME, str(task_id), _job_id=job_id)
        except RedisError:
            logger.warning("background task %s attempt %s was not queued", task_id, attempt)
            raise
