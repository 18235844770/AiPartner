import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.modules.memory.domain.enums import MemoryType
from app.modules.memory.domain.extraction import (
    ExtractedMemory,
    ExtractionCategory,
    ExtractionOutput,
    MemoryWriteAction,
    extraction_messages,
)
from app.modules.memory.services.extraction import MemoryExtractionService
from app.modules.model_adapter.domain.errors import ModelOutputError
from app.shared.database.session import dispose_engine, get_engine, get_session_factory
from tests.test_dialogue_turn import _Adapter, _client, _prepare, _suggestion


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


class _MemoryModel:
    def __init__(self, output: ExtractionOutput | None = None, error: Exception | None = None) -> None:
        self.output = output or ExtractionOutput(memories=[])
        self.error = error
        self.calls = 0
        self.messages: list[object] = []

    async def complete_structured(self, task: object, messages: list[object], result_type: object, scope: object) -> ExtractionOutput:
        del task, result_type, scope
        self.calls += 1
        self.messages = list(messages)
        if self.error is not None:
            raise self.error
        return self.output


def _item(
    category: ExtractionCategory,
    content: str,
    *,
    explicit: bool,
    memory_type: MemoryType,
    action: MemoryWriteAction = MemoryWriteAction.CREATE,
    target_memory_id: uuid.UUID | None = None,
) -> ExtractedMemory:
    return ExtractedMemory(
        action=action,
        target_memory_id=target_memory_id,
        memory_type=memory_type,
        category=category,
        explicit=explicit,
        content=content,
        summary=content,
    )


def test_extraction_prompt_lists_existing_memories_without_scores() -> None:
    messages = extraction_messages(
        "我还是喜欢喝茶",
        [{"id": "11111111-1111-4111-8111-111111111111", "category": "preference", "content": "用户喜欢喝茶", "summary": None}],
    )
    body = messages[1].content
    assert "11111111-1111-4111-8111-111111111111" in body
    assert "closeness" not in body
    assert "我还是喜欢喝茶" in body


async def _evaluate_count(message_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM background_tasks WHERE task_key = :task_key"),
            {"task_key": f"memory-evaluate:{message_id}"},
        )
    return int(count or 0)


async def _task_count(message_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM background_tasks WHERE task_key = :task_key"),
            {"task_key": f"memory-extract:{message_id}"},
        )
    return int(count or 0)


async def _run(task_id: uuid.UUID, model: _MemoryModel):
    service = MemoryExtractionService(adapter=model)

    async def handler(session: object, task: object) -> dict[str, object]:
        payload = task.payload
        return await service.extract(
            session,  # type: ignore[arg-type]
            user_id=uuid.UUID(str(payload["user_id"])),
            companion_id=task.companion_id,
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
            message_id=uuid.UUID(str(payload["message_id"])),
            task_id=task.id,
        )

    return await TaskExecutor().execute(task_id, "worker-test", {"memory_extract": handler})


@pytest.mark.asyncio
async def test_user_turn_schedules_one_extract_task(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.QUIET, False)])
    client_message_id = str(uuid.uuid4())
    async with _client(adapter) as client:
        scope = await _prepare(client)
        first = await client.post(scope.turns, json={"content": "我喜欢喝茶", "client_message_id": client_message_id})
        second = await client.post(scope.turns, json={"content": "我喜欢喝茶", "client_message_id": client_message_id})
        assert first.status_code == 201
        assert second.status_code == 200
        message_id = first.json()["user_message_id"]
    assert await _task_count(message_id) == 1


@pytest.mark.asyncio
async def test_extraction_stores_candidates_and_does_not_repeat(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "记忆提取用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "记忆陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "记忆会话"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "我明确说过喜欢喝茶，今天有点累"},
        )
        message_id = message.json()["id"]
        async with get_session_factory()() as session:
            created = await BackgroundTaskService().create(
                session,
                CreateBackgroundTaskRequest(
                    user_id=uuid.UUID(user_id),
                    companion_id=uuid.UUID(companion_id),
                    task_type=BackgroundTaskType.MEMORY_EXTRACT,
                    task_key=f"memory-extract:{message_id}",
                    queue_name="memory",
                    payload={
                        "user_id": user_id,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    },
                    max_retries=2,
                    scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
                ),
            )
        model = _MemoryModel(
            ExtractionOutput(
                memories=[
                    _item(ExtractionCategory.PREFERENCE, "用户喜欢喝茶", explicit=True, memory_type=MemoryType.SEMANTIC),
                    _item(ExtractionCategory.EMOTION, "用户当时觉得累", explicit=False, memory_type=MemoryType.SEMANTIC),
                ]
            )
        )
        finished = await _run(created.task.id, model)
        assert finished is not None
        assert finished.status == "completed"
        assert finished.result == {"created": 2, "supplemented": 0, "corrected": 0, "ignored": 0, "skipped": False}
        again = await _run(created.task.id, model)
        assert again is not None
        assert again.status == "completed"
        assert model.calls == 1
        assert await _task_count(message_id) == 1
        assert await _evaluate_count(message_id) == 1
        listed = await client.get(f"/api/users/{user_id}/companions/{companion_id}/memories")
        rows = listed.json()
        assert len(rows) == 2
        by_category = {item["memory_category"]: item for item in rows}
        tea = by_category["preference"]
        assert tea["status"] == "candidate"
        assert tea["memory_origin"] == "user_explicit"
        assert tea["is_inference"] is False
        assert tea["sources"][0]["message_id"] == message_id
        mood = by_category["emotion"]
        assert mood["status"] == "candidate"
        assert mood["memory_type"] == "episodic"
        assert mood["memory_origin"] == "ai_inference"
        assert mood["is_inference"] is True


@pytest.mark.asyncio
async def test_extraction_failure_writes_no_memory(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "记忆失败用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "记忆失败陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "失败会话"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "今天随便说说"},
        )
        message_id = message.json()["id"]
        async with get_session_factory()() as session:
            created = await BackgroundTaskService().create(
                session,
                CreateBackgroundTaskRequest(
                    user_id=uuid.UUID(user_id),
                    companion_id=uuid.UUID(companion_id),
                    task_type=BackgroundTaskType.MEMORY_EXTRACT,
                    task_key=f"memory-extract:{message_id}",
                    queue_name="memory",
                    payload={
                        "user_id": user_id,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    },
                    max_retries=2,
                    scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
                ),
            )
        finished = await _run(created.task.id, _MemoryModel(error=ModelOutputError("模型输出不符合结构")))
        assert finished is not None
        assert finished.status == "retrying"
        listed = await client.get(f"/api/users/{user_id}/companions/{companion_id}/memories")
        assert listed.json() == []
        assert await _evaluate_count(message_id) == 0


@pytest.mark.asyncio
async def test_extraction_supplements_corrects_or_ignores_existing_memories(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "记忆对照用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "记忆对照陪伴"})
        companion_id = companion.json()["id"]
        other_user = await client.post("/api/users", json={"display_name": "其他人"})
        other_companion = await client.post(
            f"/api/users/{other_user.json()['id']}/companions",
            json={"name": "别人的陪伴"},
        )
        foreign = await client.post(
            f"/api/users/{other_user.json()['id']}/companions/{other_companion.json()['id']}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "fact",
                "memory_origin": "user_explicit",
                "content": "别人住在北京",
                "change_reason": "别人的记忆",
            },
        )
        assert foreign.status_code == 201
        foreign_id = foreign.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "对照会话"},
        )
        conversation_id = conversation.json()["id"]
        tea = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "preference",
                "memory_origin": "user_explicit",
                "content": "用户喜欢喝茶",
                "change_reason": "已有偏好",
            },
        )
        city = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "fact",
                "memory_origin": "user_explicit",
                "content": "用户住在上海",
                "change_reason": "已有事实",
            },
        )
        assert tea.status_code == 201
        assert city.status_code == 201
        tea_id = tea.json()["id"]
        city_id = city.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "我喜欢喝茶，而且只喝绿茶。我不在上海，我住杭州。下周去西湖。"},
        )
        message_id = message.json()["id"]
        async with get_session_factory()() as session:
            created = await BackgroundTaskService().create(
                session,
                CreateBackgroundTaskRequest(
                    user_id=uuid.UUID(user_id),
                    companion_id=uuid.UUID(companion_id),
                    task_type=BackgroundTaskType.MEMORY_EXTRACT,
                    task_key=f"memory-extract:{message_id}",
                    queue_name="memory",
                    payload={
                        "user_id": user_id,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                    },
                    max_retries=0,
                    scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
                ),
            )
        model = _MemoryModel(
            ExtractionOutput(
                memories=[
                    _item(
                        ExtractionCategory.PREFERENCE,
                        "用户喜欢喝茶，而且只喝绿茶",
                        explicit=True,
                        memory_type=MemoryType.SEMANTIC,
                        action=MemoryWriteAction.SUPPLEMENT,
                        target_memory_id=uuid.UUID(tea_id),
                    ),
                    _item(
                        ExtractionCategory.FACT,
                        "用户住在杭州",
                        explicit=True,
                        memory_type=MemoryType.SEMANTIC,
                        action=MemoryWriteAction.CORRECT,
                        target_memory_id=uuid.UUID(city_id),
                    ),
                    _item(
                        ExtractionCategory.PLAN,
                        "用户下周去西湖",
                        explicit=True,
                        memory_type=MemoryType.EPISODIC,
                        action=MemoryWriteAction.CREATE,
                    ),
                    _item(
                        ExtractionCategory.PREFERENCE,
                        "用户喜欢喝茶",
                        explicit=True,
                        memory_type=MemoryType.SEMANTIC,
                        action=MemoryWriteAction.IGNORE,
                    ),
                    _item(
                        ExtractionCategory.FACT,
                        "别人的城市被改掉",
                        explicit=True,
                        memory_type=MemoryType.SEMANTIC,
                        action=MemoryWriteAction.CORRECT,
                        target_memory_id=uuid.UUID(foreign_id),
                    ),
                ]
            )
        )
        finished = await _run(created.task.id, model)
        assert finished is not None
        assert finished.status == "completed"
        assert finished.result == {"created": 1, "supplemented": 1, "corrected": 1, "ignored": 2, "skipped": False}
        prompt = model.messages[1].content
        assert tea_id in prompt
        assert city_id in prompt
        assert foreign_id not in prompt
        assert "closeness" not in prompt
        listed = await client.get(f"/api/users/{user_id}/companions/{companion_id}/memories")
        rows = {item["id"]: item for item in listed.json()}
        assert len(rows) == 3
        plan = next(item for item in rows.values() if item["memory_category"] == "plan")
        assert plan["status"] == "candidate"
        assert plan["current_version"]["change_type"] == "create"
        assert plan["current_version"]["version_number"] == 1
        updated_tea = rows[tea_id]
        assert updated_tea["status"] == "candidate"
        assert updated_tea["memory_origin"] == "user_explicit"
        assert updated_tea["current_version"]["version_number"] == 2
        assert updated_tea["current_version"]["change_type"] == "supplement"
        assert updated_tea["current_version"]["content"] == "用户喜欢喝茶，而且只喝绿茶"
        assert updated_tea["sources"][-1]["source_role"] == "evidence"
        assert updated_tea["sources"][-1]["message_id"] == message_id
        updated_city = rows[city_id]
        assert updated_city["status"] == "candidate"
        assert updated_city["memory_origin"] == "user_explicit"
        assert updated_city["current_version"]["version_number"] == 2
        assert updated_city["current_version"]["change_type"] == "correct"
        assert updated_city["current_version"]["content"] == "用户住在杭州"
        assert updated_city["sources"][-1]["source_role"] == "correction"
        assert updated_city["sources"][-1]["message_id"] == message_id
        foreign_again = await client.get(
            f"/api/users/{other_user.json()['id']}/companions/{other_companion.json()['id']}/memories/{foreign_id}"
        )
        assert foreign_again.json()["current_version"]["version_number"] == 1
        assert foreign_again.json()["current_version"]["content"] == "别人住在北京"
