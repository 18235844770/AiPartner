import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.modules.infrastructure.worker import relate_memory_task
from app.modules.memory.domain.enums import MemoryRelationType
from app.modules.memory.domain.relation import RelationOutput, RelationProposal, relation_messages
from app.modules.memory.services.relation import MemoryRelationService
from app.modules.model_adapter.domain.errors import ModelOutputError
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


def test_relation_prompt_links_existing_memories_without_new_facts() -> None:
    messages = relation_messages(
        "我哥哥也住在杭州",
        [{"id": "11111111-1111-4111-8111-111111111111", "content": "用户住在杭州", "from_message": False}],
    )
    assert "不要编造新记忆" in messages[0].content
    assert "from_message" in messages[0].content
    assert "11111111-1111-4111-8111-111111111111" in messages[1].content
    assert "closeness" not in messages[1].content


async def test_relation_handler_rejects_a_bad_payload() -> None:
    task = type("Task", (), {"companion_id": uuid.uuid4(), "payload": {"user_id": "bad"}})()
    with pytest.raises(ValueError):
        await relate_memory_task(None, task)


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


class _LinkModel:
    def __init__(self, output: RelationOutput | None = None, error: Exception | None = None) -> None:
        self.output = output or RelationOutput(relations=[])
        self.error = error
        self.calls = 0

    async def complete_structured(self, task: object, messages: list[object], result_type: object, scope: object) -> RelationOutput:
        del task, result_type, scope
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


def _proposal(source_id: str, target_id: str) -> RelationProposal:
    return RelationProposal(
        source_memory_id=uuid.UUID(source_id),
        target_memory_id=uuid.UUID(target_id),
        relation_type=MemoryRelationType.RELATED_TO,
        strength=Decimal("0.800"),
        description="两件事都提到杭州",
    )


async def _run(task_id: uuid.UUID, model: _LinkModel):
    service = MemoryRelationService(adapter=model)

    async def handler(session: object, task: object) -> dict[str, object]:
        payload = task.payload
        return await service.relate(
            session,  # type: ignore[arg-type]
            user_id=uuid.UUID(str(payload["user_id"])),
            companion_id=task.companion_id,
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
            message_id=uuid.UUID(str(payload["message_id"])),
            task_id=task.id,
        )

    return await TaskExecutor().execute(task_id, "worker-test", {"memory_relation": handler})


async def _relation_rows(source_id: str) -> list[tuple[str, str, str]]:
    async with get_engine().connect() as connection:
        rows = await connection.execute(
            text(
                """
                SELECT target_memory_id::text, relation_type, description
                FROM memory_relations
                WHERE source_memory_id = :source_id
                """
            ),
            {"source_id": source_id},
        )
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows.all()]


async def _proactive_event_count(message_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM background_tasks WHERE task_key = :task_key"),
            {"task_key": f"proactive-check:event:relation:{message_id}"},
        )
    return int(count or 0)


@pytest.mark.asyncio
async def test_relation_links_only_memories_the_message_can_reach(database_ready: None) -> None:
    scope = await _scope("关联用户", "我哥哥也住在杭州")
    outsider = await _memory(scope, "用户养了一只猫", message_id=None)
    model = _LinkModel(
        RelationOutput(
            relations=[
                _proposal(scope["current_id"], scope["older_id"]),
                _proposal(scope["current_id"], scope["current_id"]),
                _proposal(scope["older_id"], outsider),
                _proposal(scope["current_id"], str(uuid.uuid4())),
            ]
        )
    )
    finished = await _run(await _task(scope), model)
    assert finished is not None
    assert finished.status == "completed"
    assert model.calls == 1
    assert await _relation_rows(scope["current_id"]) == [(scope["older_id"], "related_to", "两件事都提到杭州")]
    again = await _run(await _task(scope, key_suffix="-again"), model)
    assert again is not None
    assert again.status == "completed"
    assert model.calls == 2
    assert await _relation_rows(scope["current_id"]) == [(scope["older_id"], "related_to", "两件事都提到杭州")]
    assert await _proactive_event_count(scope["message_id"]) == 1


@pytest.mark.asyncio
async def test_relation_model_failure_keeps_the_memories(database_ready: None) -> None:
    scope = await _scope("关联失败用户", "今天随便说说")
    model = _LinkModel(error=ModelOutputError("模型输出不符合结构"))
    finished = await _run(await _task(scope), model)
    assert finished is not None
    assert finished.status == "retrying"
    assert await _relation_rows(scope["current_id"]) == []
    async with get_engine().connect() as connection:
        status = await connection.scalar(text("SELECT status FROM memories WHERE id = :memory_id"), {"memory_id": scope["current_id"]})
    assert status == "candidate"
    assert await _proactive_event_count(scope["message_id"]) == 0


async def _scope(name: str, content: str) -> dict[str, str]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": name})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "关联陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "关联会话"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": content},
        )
        message_id = message.json()["id"]
        older_id = await _memory(
            {"user_id": user_id, "companion_id": companion_id},
            "用户住在杭州",
            message_id=None,
            client=client,
        )
        current_id = await _memory(
            {"user_id": user_id, "companion_id": companion_id},
            "用户的哥哥住在杭州",
            message_id=message_id,
            client=client,
        )
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "older_id": older_id,
        "current_id": current_id,
    }


async def _memory(scope: dict[str, str], content: str, message_id: str | None, client: AsyncClient | None = None) -> str:
    body: dict[str, object] = {
        "memory_type": "semantic",
        "memory_category": "fact",
        "memory_origin": "user_explicit",
        "content": content,
        "change_reason": "关联测试",
    }
    if message_id is not None:
        body["sources"] = [{"source_type": "message", "source_role": "evidence", "message_id": message_id}]
    owns_client = client is None
    if client is None:
        app = create_app()
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        created = await client.post(
            f"/api/users/{scope['user_id']}/companions/{scope['companion_id']}/memories",
            json=body,
        )
        assert created.status_code == 201
        memory_id = created.json()["id"]
        assert isinstance(memory_id, str)
        return memory_id
    finally:
        if owns_client:
            await client.aclose()


async def _task(scope: dict[str, str], key_suffix: str = "") -> uuid.UUID:
    async with get_session_factory()() as session:
        created = await BackgroundTaskService().create(
            session,
            CreateBackgroundTaskRequest(
                user_id=uuid.UUID(scope["user_id"]),
                companion_id=uuid.UUID(scope["companion_id"]),
                task_type=BackgroundTaskType.MEMORY_RELATION,
                task_key=f"memory-relation:{scope['message_id']}{key_suffix}",
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
