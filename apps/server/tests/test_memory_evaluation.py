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
from app.modules.memory.domain.evaluation import (
    EvaluationOutput,
    MemoryScore,
    evaluation_messages,
    importance_points,
    quality_score,
)
from app.modules.memory.services.evaluation import MemoryEvaluationService
from app.modules.model_adapter.domain.errors import ModelOutputError
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


def test_quality_score_uses_the_documented_weights() -> None:
    score = quality_score(
        importance=Decimal("0.800"),
        stability=Decimal("0.600"),
        repetition=Decimal("0.200"),
        relatedness=Decimal("0.500"),
        freshness=Decimal("0.700"),
    )
    assert score == Decimal("0.590")
    assert importance_points(Decimal("0.875")) == 88
    assert importance_points(Decimal("1")) == 100


def test_evaluation_prompt_names_memories_without_relationship_scores() -> None:
    messages = evaluation_messages(
        "我喜欢喝茶",
        [{"id": "11111111-1111-4111-8111-111111111111", "category": "preference", "content": "用户喜欢喝茶"}],
    )
    assert "正式记忆" in messages[0].content
    assert "11111111-1111-4111-8111-111111111111" in messages[1].content
    assert "closeness" not in messages[1].content


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


class _ScoreModel:
    def __init__(self, output: EvaluationOutput | None = None, error: Exception | None = None) -> None:
        self.output = output or EvaluationOutput(evaluations=[])
        self.error = error
        self.calls = 0
        self.messages: list[object] = []

    async def complete_structured(self, task: object, messages: list[object], result_type: object, scope: object) -> EvaluationOutput:
        del task, result_type, scope
        self.calls += 1
        self.messages = list(messages)
        if self.error is not None:
            raise self.error
        return self.output


def _score(memory_id: str) -> MemoryScore:
    return MemoryScore(
        memory_id=uuid.UUID(memory_id),
        importance=Decimal("0.800"),
        stability=Decimal("0.600"),
        repetition=Decimal("0.200"),
        relatedness=Decimal("0.500"),
        freshness=Decimal("0.700"),
        confidence=Decimal("0.900"),
        relevance=Decimal("0.400"),
        reason="用户明确说过，但目前只出现一次",
    )


async def _run(task_id: uuid.UUID, model: _ScoreModel):
    service = MemoryEvaluationService(adapter=model)

    async def handler(session: object, task: object) -> dict[str, object]:
        payload = task.payload
        return await service.evaluate(
            session,  # type: ignore[arg-type]
            user_id=uuid.UUID(str(payload["user_id"])),
            companion_id=task.companion_id,
            conversation_id=uuid.UUID(str(payload["conversation_id"])),
            message_id=uuid.UUID(str(payload["message_id"])),
            task_id=task.id,
        )

    return await TaskExecutor().execute(task_id, "worker-test", {"memory_evaluate": handler})


async def _memory_row(memory_id: str) -> tuple[object, ...]:
    async with get_engine().connect() as connection:
        row = await connection.execute(
            text(
                """
                SELECT importance, stability, confidence, relevance, status, memory_origin
                FROM memories WHERE id = :memory_id
                """
            ),
            {"memory_id": memory_id},
        )
    return tuple(row.one())


@pytest.mark.asyncio
async def test_evaluation_records_scores_without_promoting(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "评分用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "评分陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "评分会话"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "我明确说过喜欢喝茶"},
        )
        message_id = message.json()["id"]
        created = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "preference",
                "memory_origin": "user_explicit",
                "content": "用户喜欢喝茶",
                "change_reason": "待评分",
                "sources": [{"source_type": "message", "source_role": "evidence", "message_id": message_id}],
            },
        )
        untouched = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "fact",
                "memory_origin": "user_explicit",
                "content": "用户住在杭州",
                "change_reason": "不在本次评分范围",
            },
        )
        assert created.status_code == 201
        assert untouched.status_code == 201
        memory_id = created.json()["id"]
        other_id = untouched.json()["id"]
        async with get_session_factory()() as session:
            task = await BackgroundTaskService().create(
                session,
                CreateBackgroundTaskRequest(
                    user_id=uuid.UUID(user_id),
                    companion_id=uuid.UUID(companion_id),
                    task_type=BackgroundTaskType.MEMORY_EVALUATE,
                    task_key=f"memory-evaluate:{message_id}",
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
        model = _ScoreModel(
            EvaluationOutput(
                evaluations=[
                    _score(memory_id),
                    _score("22222222-2222-4222-8222-222222222222"),
                ]
            )
        )
        finished = await _run(task.task.id, model)
        assert finished is not None
        assert finished.status == "completed"
        assert finished.result["evaluated"] == 1
        assert finished.result["ignored"] == 1
        assert finished.result["skipped"] is False
        assert finished.result["scores"][0]["score"] == "0.590"
        assert finished.result["scores"][0]["status"] == "candidate"
        assert model.calls == 1
        assert memory_id in model.messages[1].content
        assert other_id not in model.messages[1].content
        again = await _run(task.task.id, model)
        assert again is not None
        assert again.status == "completed"
        assert model.calls == 1
        listed = await client.get(f"/api/users/{user_id}/companions/{companion_id}/memories/{memory_id}")
        body = listed.json()
        assert body["status"] == "candidate"
        assert body["memory_origin"] == "user_explicit"
        assert body["importance"] == 80
        assert body["current_version"]["version_number"] == 1
        assert body["current_version"]["content"] == "用户喜欢喝茶"
        importance, stability, confidence, relevance, status, origin = await _memory_row(memory_id)
        assert importance == 80
        assert stability == Decimal("0.600")
        assert confidence == Decimal("0.900")
        assert relevance == Decimal("0.400")
        assert status == "candidate"
        assert origin == "user_explicit"
        other_importance, *_rest = await _memory_row(other_id)
        assert other_importance == 50


@pytest.mark.asyncio
async def test_evaluation_failure_keeps_default_scores(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "评分失败用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "评分失败陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "失败评分"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "今天随便说说"},
        )
        message_id = message.json()["id"]
        created = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "fact",
                "memory_origin": "user_explicit",
                "content": "用户提到今天",
                "change_reason": "待评分",
                "sources": [{"source_type": "message", "source_role": "evidence", "message_id": message_id}],
            },
        )
        memory_id = created.json()["id"]
        async with get_session_factory()() as session:
            task = await BackgroundTaskService().create(
                session,
                CreateBackgroundTaskRequest(
                    user_id=uuid.UUID(user_id),
                    companion_id=uuid.UUID(companion_id),
                    task_type=BackgroundTaskType.MEMORY_EVALUATE,
                    task_key=f"memory-evaluate:{message_id}",
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
        finished = await _run(task.task.id, _ScoreModel(error=ModelOutputError("模型输出不符合结构")))
        assert finished is not None
        assert finished.status == "retrying"
        importance, _stability, _confidence, _relevance, status, _origin = await _memory_row(memory_id)
        assert importance == 50
        assert status == "candidate"
