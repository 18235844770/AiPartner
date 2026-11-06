import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.shared.database.session import dispose_engine, get_engine

pytestmark = pytest.mark.asyncio

TRACE_ID = "22222222-2222-4222-8222-222222222222"
TASK_KEY = "debug-scope-task"


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


async def _remove_fixtures() -> None:
    async with get_engine().begin() as connection:
        await connection.execute(
            text("DELETE FROM model_call_logs WHERE trace_id = :trace_id"),
            {"trace_id": TRACE_ID},
        )
        await connection.execute(
            text("DELETE FROM background_tasks WHERE task_key = :task_key"),
            {"task_key": TASK_KEY},
        )


async def test_companion_lists_are_scoped(database_ready: None) -> None:
    await _remove_fixtures()
    try:
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            owner = await client.post("/api/users", json={"display_name": "调试主人"})
            outsider = await client.post("/api/users", json={"display_name": "调试外人"})
            assert owner.status_code == 201
            assert outsider.status_code == 201
            owner_id = owner.json()["id"]
            outsider_id = outsider.json()["id"]
            companion = await client.post(f"/api/users/{owner_id}/companions", json={"name": "调试陪伴"})
            other = await client.post(f"/api/users/{owner_id}/companions", json={"name": "另一个陪伴"})
            assert companion.status_code == 201
            assert other.status_code == 201
            companion_id = companion.json()["id"]
            other_id = other.json()["id"]

            logged = await client.post(
                "/api/model-call-logs",
                json={
                    "user_id": owner_id,
                    "companion_id": companion_id,
                    "trace_id": TRACE_ID,
                    "task_type": "decision",
                    "provider": "deepseek",
                    "model_name": "deepseek-chat",
                    "status": "success",
                    "latency_ms": 12,
                    "input_tokens": 3,
                    "output_tokens": 1,
                    "created_at": "2026-11-06T07:00:00Z",
                    "completed_at": "2026-11-06T07:00:01Z",
                },
            )
            assert logged.status_code == 201
            created = await client.post(
                "/api/background-tasks",
                json={
                    "user_id": owner_id,
                    "companion_id": companion_id,
                    "task_type": "memory_extract",
                    "task_key": TASK_KEY,
                    "queue_name": "memory",
                    "max_retries": 1,
                    "scheduled_at": "2026-11-06T07:00:00Z",
                },
            )
            assert created.status_code == 201

            base = f"/api/users/{owner_id}/companions/{companion_id}"
            calls = await client.get(f"{base}/model-call-logs")
            tasks = await client.get(f"{base}/background-tasks")
            assert calls.status_code == 200
            assert tasks.status_code == 200
            assert [item["trace_id"] for item in calls.json()] == [TRACE_ID]
            assert [item["task_key"] for item in tasks.json()] == [TASK_KEY]

            empty_calls = await client.get(f"/api/users/{owner_id}/companions/{other_id}/model-call-logs")
            empty_tasks = await client.get(f"/api/users/{owner_id}/companions/{other_id}/background-tasks")
            assert empty_calls.status_code == 200
            assert empty_tasks.status_code == 200
            assert empty_calls.json() == []
            assert empty_tasks.json() == []

            denied_calls = await client.get(f"/api/users/{outsider_id}/companions/{companion_id}/model-call-logs")
            denied_tasks = await client.get(f"/api/users/{outsider_id}/companions/{companion_id}/background-tasks")
            assert denied_calls.status_code == 404
            assert denied_tasks.status_code == 404
            assert uuid.UUID(companion_id)
    finally:
        await _remove_fixtures()
