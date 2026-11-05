import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.repositories.infrastructure_repository import BackgroundTaskRepository
from app.modules.infrastructure.repositories.models import BackgroundTask
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_dispatcher import TaskDispatcher
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.shared.database.session import dispose_engine, get_engine, get_session_factory
from app.shared.redis.client import ping_redis


class _Queue:
    def __init__(self, error: Exception | None = None) -> None:
        self.jobs: list[tuple[uuid.UUID, int]] = []
        self._error = error

    async def enqueue(self, task_id: uuid.UUID, attempt: int) -> None:
        if self._error is not None:
            raise self._error
        self.jobs.append((task_id, attempt))


@pytest.fixture
async def database_ready():
    await dispose_engine()
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        await dispose_engine()
        pytest.skip(f"PostgreSQL 不可用，跳过集成测试: {exc}")
    try:
        yield
    finally:
        await dispose_engine()


def test_worker_entry_dispatches_and_executes() -> None:
    from app.modules.infrastructure.worker import HANDLERS, WorkerSettings

    assert WorkerSettings.functions[0].name == "execute_background_task"
    assert set(HANDLERS) == {"memory_extract", "memory_evaluate"}
    assert WorkerSettings.cron_jobs[0].coroutine.__name__ == "dispatch_outbox"
    assert WorkerSettings.cron_jobs[0].run_at_startup is True


async def _create(task_key: str, scheduled_at: datetime, max_retries: int = 1) -> uuid.UUID:
    async with get_session_factory()() as session:
        created = await BackgroundTaskService().create(
            session,
            CreateBackgroundTaskRequest(
                task_type=BackgroundTaskType.MEMORY_EXTRACT,
                task_key=task_key,
                queue_name="memory",
                payload={"source": "dispatch-test"},
                max_retries=max_retries,
                scheduled_at=scheduled_at,
            ),
        )
    return created.task.id


async def _load(task_id: uuid.UUID) -> BackgroundTask:
    async with get_session_factory()() as session:
        async with session.begin():
            task = await BackgroundTaskRepository().get(session, task_id)
    assert task is not None
    return task


async def _delete(task_key: str) -> None:
    async with get_engine().begin() as connection:
        await connection.execute(text("DELETE FROM background_tasks WHERE task_key = :task_key"), {"task_key": task_key})


@pytest.mark.asyncio
async def test_redis_outage_keeps_the_task_and_a_second_dispatch_is_not_duplicated(database_ready: None) -> None:
    task_key = f"dispatch-test-{uuid.uuid4()}"
    task_id = await _create(task_key, datetime.now(UTC) - timedelta(seconds=1))
    try:
        dispatcher = TaskDispatcher()
        blocked = _Queue(ConnectionError("redis down"))
        assert await dispatcher.dispatch_task(blocked, task_id) is False
        assert blocked.jobs == []
        assert (await _load(task_id)).status == "pending"

        queue = _Queue()
        assert await dispatcher.dispatch_task(queue, task_id) is True
        assert queue.jobs == [(task_id, 0)]
        queued = await _load(task_id)
        assert queued.status == "queued"
        assert queued.dispatched_at is not None
        assert await dispatcher.dispatch_task(queue, task_id) is False
        assert queue.jobs == [(task_id, 0)]
    finally:
        await _delete(task_key)


@pytest.mark.asyncio
async def test_future_task_is_not_dispatched(database_ready: None) -> None:
    task_key = f"dispatch-test-{uuid.uuid4()}"
    task_id = await _create(task_key, datetime.now(UTC) + timedelta(hours=1))
    try:
        queue = _Queue()
        assert await TaskDispatcher().dispatch_task(queue, task_id) is False
        assert queue.jobs == []
        assert (await _load(task_id)).status == "pending"
    finally:
        await _delete(task_key)


@pytest.mark.asyncio
async def test_duplicate_execution_runs_the_handler_once_and_failure_can_be_retried(database_ready: None) -> None:
    task_key = f"dispatch-test-{uuid.uuid4()}"
    task_id = await _create(task_key, datetime.now(UTC) - timedelta(seconds=1))
    calls: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()
    first: asyncio.Task[BackgroundTask | None] | None = None
    second: asyncio.Task[BackgroundTask | None] | None = None

    async def slow(session: object, task: BackgroundTask) -> dict[str, object]:
        del session
        calls.append(task.task_key)
        started.set()
        await release.wait()
        return {"applied": True}

    try:
        executor = TaskExecutor()
        first = asyncio.create_task(executor.execute(task_id, "worker-a", {"memory_extract": slow}))
        await started.wait()
        second = asyncio.create_task(executor.execute(task_id, "worker-b", {"memory_extract": slow}))
        await asyncio.sleep(0.2)
        assert calls == [task_key]
        release.set()
        assert (await first).status == "completed"
        assert (await second).status == "completed"
        assert calls == [task_key]
        assert (await _load(task_id)).result == {"applied": True}
    finally:
        release.set()
        if first is not None:
            await first
        if second is not None:
            await second
        await _delete(task_key)

    calls.clear()
    retry_key = f"dispatch-test-{uuid.uuid4()}"
    retry_id = await _create(retry_key, datetime.now(UTC) - timedelta(seconds=1))

    async def fail(session: object, task: BackgroundTask) -> dict[str, object]:
        del session, task
        raise RuntimeError("暂时失败")

    async def succeed(session: object, task: BackgroundTask) -> dict[str, object]:
        del session
        calls.append(task.task_key)
        return {"applied": True}

    try:
        failed = await TaskExecutor().execute(retry_id, "worker-a", {"memory_extract": fail})
        assert failed is not None
        assert failed.status == "retrying"
        assert failed.retry_count == 1
        assert failed.dispatched_at is None
        queue = _Queue()
        assert await TaskDispatcher().dispatch_task(queue, retry_id) is True
        assert queue.jobs == [(retry_id, 1)]
        completed = await TaskExecutor().execute(retry_id, "worker-a", {"memory_extract": succeed})
        assert completed is not None
        assert completed.status == "completed"
        assert calls == [retry_key]
    finally:
        await _delete(retry_key)


@pytest.mark.asyncio
async def test_missing_handler_does_not_invent_a_result(database_ready: None) -> None:
    task_key = f"dispatch-test-{uuid.uuid4()}"
    task_id = await _create(task_key, datetime.now(UTC) - timedelta(seconds=1), max_retries=0)
    try:
        finished = await TaskExecutor().execute(task_id, "worker-a", {})
        assert finished is not None
        assert finished.status == "failed"
        assert finished.result is None
        assert finished.error_message == "任务执行器尚未实现"
    finally:
        await _delete(task_key)


@pytest.mark.asyncio
async def test_real_redis_accepts_one_job_per_attempt(database_ready: None) -> None:
    if not await ping_redis():
        pytest.skip("Redis 不可用，跳过投递测试")
    from arq import create_pool
    from arq.connections import RedisSettings
    from arq.constants import default_queue_name, job_key_prefix, result_key_prefix

    from app.config.settings import get_settings
    from app.modules.infrastructure.services.task_queue import ArqTaskQueue

    task_key = f"dispatch-test-{uuid.uuid4()}"
    task_id = await _create(task_key, datetime.now(UTC) - timedelta(seconds=1))
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    job_id = f"{task_id}:0"
    try:
        queue = ArqTaskQueue(pool)
        dispatcher = TaskDispatcher()
        assert await dispatcher.dispatch_task(queue, task_id) is True
        await queue.enqueue(task_id, 0)
        assert await pool.exists(job_key_prefix + job_id) == 1
        assert (await _load(task_id)).status == "queued"
        assert await dispatcher.dispatch_task(queue, task_id) is False
    finally:
        await pool.delete(job_key_prefix + job_id, result_key_prefix + job_id)
        await pool.zrem(default_queue_name, job_id)
        await pool.aclose()
        await _delete(task_key)
