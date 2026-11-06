import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from app.main import create_app
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.modules.infrastructure.worker import summarize_memory_task
from app.modules.memory.api.context_schemas import OpenThreadInput, SaveWorkingMemoryRequest
from app.modules.memory.domain.enums import OpenThreadStatus
from app.modules.memory.domain.summary import SummaryOutput, SummaryThread, summary_messages
from app.modules.memory.services.context_service import MemoryContextService
from app.modules.memory.services.summary import MemorySummaryService
from app.modules.model_adapter.domain.errors import ModelOutputError
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


def test_summary_prompt_keeps_facts_and_topic_out_of_the_output() -> None:
    messages = summary_messages(
        {
            "current_topic": "接口设计",
            "summary": None,
            "open_threads": [],
            "messages": [{"sender": "user", "content": "接口还没定"}],
        }
    )
    assert "不要把它写成可以长期保存的用户事实" in messages[0].content
    assert "不要输出它" in messages[0].content
    assert "接口还没定" in messages[1].content
    with pytest.raises(ValidationError):
        SummaryOutput.model_validate({"summary": "还在聊接口", "current_topic": "别的话题", "open_threads": []})


async def test_summary_handler_rejects_a_bad_payload() -> None:
    task = type("Task", (), {"companion_id": uuid.uuid4(), "payload": {"user_id": "bad"}})()
    with pytest.raises(ValueError):
        await summarize_memory_task(None, task)


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


class _SummaryModel:
    def __init__(self, output: SummaryOutput | None = None, error: Exception | None = None) -> None:
        self.output = output or SummaryOutput(summary="还在讨论", open_threads=[])
        self.error = error
        self.calls = 0
        self.seen: list[str] = []

    async def complete_structured(self, task: object, messages: list[object], result_type: object, scope: object) -> SummaryOutput:
        del task, result_type, scope
        self.calls += 1
        content = getattr(messages[1], "content", "")
        self.seen.append(content if isinstance(content, str) else "")
        if self.error is not None:
            raise self.error
        return self.output


def _output(summary: str, threads: list[tuple[str, OpenThreadStatus]]) -> SummaryOutput:
    return SummaryOutput(
        summary=summary,
        open_threads=[SummaryThread(title=title, status=status) for title, status in threads],
    )


async def _run(task_id: uuid.UUID, model: _SummaryModel):
    service = MemorySummaryService(adapter=model)

    async def handler(session: object, task: object) -> dict[str, object]:
        payload = task.payload
        return await service.summarize(
            session,  # type: ignore[arg-type]
            user_id=uuid.UUID(str(payload["user_id"])),
            companion_id=task.companion_id,
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
            message_id=uuid.UUID(str(payload["message_id"])),
            task_id=task.id,
        )

    return await TaskExecutor().execute(task_id, "worker-test", {"memory_summarize": handler})


async def _working(scope: dict[str, str]) -> dict[str, object]:
    async with get_session_factory()() as session:
        row = await MemoryContextService().get_working(
            session,
            uuid.UUID(scope["user_id"]),
            uuid.UUID(scope["companion_id"]),
            uuid.UUID(scope["conversation_id"]),
        )
        if row is None:
            return {}
        return {
            "summary": row.summary,
            "current_topic": row.current_topic,
            "version": row.version,
            "threads": [dict(item) for item in row.open_threads if isinstance(item, dict)],
        }


async def _memory_count(companion_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM memories WHERE companion_id = :companion_id"),
            {"companion_id": companion_id},
        )
    return int(count or 0)


async def _scope(name: str) -> dict[str, str]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": name})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "摘要陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "摘要会话"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "接口还没定，我想继续聊"},
        )
        message_id = message.json()["id"]
        await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "companion", "content": "我们先把范围定下来"},
        )
        failed = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "这段失败了不要写进摘要"},
        )
    async with get_engine().begin() as connection:
        await connection.execute(
            text("UPDATE messages SET status = 'failed' WHERE id = :message_id"),
            {"message_id": failed.json()["id"]},
        )
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
    }


async def _task(scope: dict[str, str], key_suffix: str = "") -> uuid.UUID:
    async with get_session_factory()() as session:
        created = await BackgroundTaskService().create(
            session,
            CreateBackgroundTaskRequest(
                user_id=uuid.UUID(scope["user_id"]),
                companion_id=uuid.UUID(scope["companion_id"]),
                task_type=BackgroundTaskType.MEMORY_SUMMARIZE,
                task_key=f"memory-summarize:{scope['message_id']}{key_suffix}",
                queue_name="memory",
                payload={
                    "user_id": scope["user_id"],
                    "message_id": scope["message_id"],
                    "conversation_id": scope["conversation_id"],
                },
                max_retries=2,
                scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
        )
    return created.task.id


@pytest.mark.asyncio
async def test_summary_updates_working_memory_without_replacing_the_topic(database_ready: None) -> None:
    scope = await _scope("摘要用户")
    first_model = _SummaryModel(
        _output(
            "还在讨论接口范围",
            [("待确认范围", OpenThreadStatus.OPEN), ("已经结束的旧事", OpenThreadStatus.CLOSED)],
        )
    )
    created = await _run(await _task(scope), first_model)
    assert created is not None
    assert created.status == "completed"
    assert created.result == {"summarized": True, "version": 1}
    assert first_model.calls == 1
    assert "接口还没定，我想继续聊" in first_model.seen[0]
    assert "我们先把范围定下来" in first_model.seen[0]
    assert "这段失败了不要写进摘要" not in first_model.seen[0]
    opened = await _working(scope)
    assert opened["summary"] == "还在讨论接口范围"
    assert opened["current_topic"] is None
    assert opened["threads"] == [{"title": "待确认范围", "status": "open", "message_id": None}]
    assert await _memory_count(scope["companion_id"]) == 0

    async with get_session_factory()() as session:
        await MemoryContextService().save_working(
            session,
            uuid.UUID(scope["user_id"]),
            uuid.UUID(scope["companion_id"]),
            uuid.UUID(scope["conversation_id"]),
            SaveWorkingMemoryRequest(
                summary="还在讨论接口范围",
                current_topic="接口设计",
                open_threads=[
                    OpenThreadInput(title="待确认范围", status=OpenThreadStatus.OPEN),
                    OpenThreadInput(
                        title="接口还没定",
                        status=OpenThreadStatus.OPEN,
                        message_id=uuid.UUID(scope["message_id"]),
                    ),
                ],
                version=1,
            ),
        )
    second_model = _SummaryModel(
        _output(
            "范围还没定",
            [("接口还没定", OpenThreadStatus.CLOSED), ("待确认范围", OpenThreadStatus.OPEN)],
        )
    )
    updated = await _run(await _task(scope, "-topic"), second_model)
    assert updated is not None
    assert updated.status == "completed"
    merged = await _working(scope)
    assert merged["summary"] == "范围还没定"
    assert merged["current_topic"] == "接口设计"
    assert merged["version"] == 3
    assert {item["title"]: item["status"] for item in merged["threads"]} == {
        "待确认范围": "open",
        "接口还没定": "closed",
    }
    closed = next(item for item in merged["threads"] if item["title"] == "接口还没定")
    assert closed["message_id"] == scope["message_id"]
    again = await _run(await _task(scope, "-again"), second_model)
    assert again is not None
    assert again.status == "completed"
    repeated = await _working(scope)
    assert len(repeated["threads"]) == 2
    assert repeated["current_topic"] == "接口设计"
    assert await _memory_count(scope["companion_id"]) == 0


@pytest.mark.asyncio
async def test_summary_model_failure_keeps_the_working_memory(database_ready: None) -> None:
    scope = await _scope("摘要失败用户")
    async with get_session_factory()() as session:
        await MemoryContextService().save_working(
            session,
            uuid.UUID(scope["user_id"]),
            uuid.UUID(scope["companion_id"]),
            uuid.UUID(scope["conversation_id"]),
            SaveWorkingMemoryRequest(current_topic="接口设计"),
        )
    model = _SummaryModel(error=ModelOutputError("模型输出不符合结构"))
    finished = await _run(await _task(scope), model)
    assert finished is not None
    assert finished.status == "retrying"
    kept = await _working(scope)
    assert kept["summary"] is None
    assert kept["current_topic"] == "接口设计"
    assert kept["version"] == 1


@pytest.mark.asyncio
async def test_summary_skips_archived_or_unusable_messages(database_ready: None) -> None:
    scope = await _scope("摘要跳过用户")
    async with get_session_factory()() as session:
        await MemoryContextService().save_working(
            session,
            uuid.UUID(scope["user_id"]),
            uuid.UUID(scope["companion_id"]),
            uuid.UUID(scope["conversation_id"]),
            SaveWorkingMemoryRequest(summary="旧摘要", current_topic="旧话题", archived=True),
        )
    model = _SummaryModel(_output("新摘要", []))
    archived = await _run(await _task(scope), model)
    assert archived is not None
    assert archived.status == "completed"
    assert archived.result == {"summarized": False, "reason": "archived"}
    assert model.calls == 0
    kept = await _working(scope)
    assert kept["summary"] == "旧摘要"
    assert kept["current_topic"] == "旧话题"

    async with get_engine().begin() as connection:
        await connection.execute(
            text("UPDATE messages SET status = 'failed' WHERE conversation_id = :conversation_id"),
            {"conversation_id": scope["conversation_id"]},
        )
        await connection.execute(
            text("UPDATE working_memories SET archived_at = NULL WHERE conversation_id = :conversation_id"),
            {"conversation_id": scope["conversation_id"]},
        )
    skipped = await _run(await _task(scope, "-empty"), model)
    assert skipped is not None
    assert skipped.status == "completed"
    assert skipped.result == {"summarized": False, "reason": "no_messages"}
    assert model.calls == 0
    still = await _working(scope)
    assert still["summary"] == "旧摘要"
