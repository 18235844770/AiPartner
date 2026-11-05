import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.shared.database.session import dispose_engine, get_engine
from tests.model_config_parking import park_model_config, restore_model_config


pytestmark = pytest.mark.asyncio


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
            text(
                """
                DELETE FROM model_call_logs
                WHERE trace_id = '11111111-1111-4111-8111-111111111111'
                   OR config_id IN (SELECT id FROM model_configs WHERE config_key = 'decision_model')
                   OR background_task_id IN (
                        SELECT id FROM background_tasks
                        WHERE task_key IN ('memory-embedding-1', 'memory-embedding-foreign')
                   )
                """
            )
        )
        await connection.execute(
            text(
                """
                DELETE FROM background_tasks
                WHERE task_key IN ('memory-embedding-1', 'memory-embedding-foreign')
                """
            )
        )
        await connection.execute(text("DELETE FROM model_configs WHERE config_key = 'decision_model'"))


async def test_config_versions_call_logs_and_task_retries(database_ready: None) -> None:
    parked = await park_model_config("decision_model")
    await _remove_fixtures()
    try:
        await _exercise_config_versions()
    finally:
        await _remove_fixtures()
        await restore_model_config(*parked)


async def _exercise_config_versions() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        secret = await client.post(
            "/api/model-configs",
            json={
                "config_key": "decision_model",
                "model_name": "pending-verification",
                "parameters": {"api_key": "hidden"},
            },
        )
        assert secret.status_code == 422

        created = await client.post(
            "/api/model-configs",
            json={
                "config_key": "decision_model",
                "model_name": "pending-verification",
                "parameters": {"temperature": 0.2},
            },
        )
        assert created.status_code == 201
        assert created.json()["provider"] == "deepseek"
        assert created.json()["task_type"] == "decision"
        assert created.json()["version"] == 1
        again = await client.post(
            "/api/model-configs",
            json={"config_key": "decision_model", "model_name": "pending-verification"},
        )
        assert again.status_code == 409

        revised = await client.post(
            "/api/model-configs/decision_model/versions",
            json={"model_name": "still-unverified", "parameters": {"temperature": 0.1}, "is_default": True},
        )
        assert revised.status_code == 201
        assert revised.json()["version"] == 2
        listed = await client.get("/api/model-configs")
        versions = [item for item in listed.json() if item["config_key"] == "decision_model"]
        assert [item["version"] for item in versions] == [2, 1]
        assert versions[0]["is_default"] is True
        assert versions[1]["is_default"] is False
        assert versions[1]["model_name"] == "pending-verification"

        rolled = await client.post("/api/model-configs/decision_model/rollback", json={"version": 1})
        assert rolled.status_code == 200
        assert rolled.json()["version"] == 1
        assert rolled.json()["is_default"] is True
        assert rolled.json()["model_name"] == "pending-verification"

        trace_id = "11111111-1111-4111-8111-111111111111"
        missing_error = await client.post(
            "/api/model-call-logs",
            json={
                "trace_id": trace_id,
                "task_type": "decision",
                "provider": "deepseek",
                "model_name": "pending-verification",
                "status": "failed",
                "latency_ms": 20,
                "created_at": "2026-11-05T14:00:00Z",
                "completed_at": "2026-11-05T14:00:01Z",
            },
        )
        assert missing_error.status_code == 422
        logged = await client.post(
            "/api/model-call-logs",
            json={
                "trace_id": trace_id,
                "config_id": created.json()["id"],
                "task_type": "decision",
                "provider": "deepseek",
                "model_name": "pending-verification",
                "status": "success",
                "latency_ms": 30,
                "input_tokens": 12,
                "output_tokens": 4,
                "created_at": "2026-11-05T14:00:00Z",
                "completed_at": "2026-11-05T14:00:01Z",
            },
        )
        assert logged.status_code == 201
        assert "prompt" not in logged.json()
        traced = await client.get("/api/model-call-logs", params={"trace_id": trace_id})
        assert traced.status_code == 200
        assert len(traced.json()) == 1

        user = await client.post("/api/users", json={"display_name": "任务用户"})
        companion = await client.post(f"/api/users/{user.json()['id']}/companions", json={"name": "任务陪伴"})
        outsider = await client.post("/api/users", json={"display_name": "其他用户"})
        foreign = await client.post(
            "/api/background-tasks",
            json={
                "user_id": outsider.json()["id"],
                "companion_id": companion.json()["id"],
                "task_type": "memory_embedding",
                "task_key": "memory-embedding-foreign",
                "queue_name": "memory",
                "max_retries": 1,
                "scheduled_at": "2026-11-05T14:00:00Z",
            },
        )
        assert foreign.status_code == 404

        body = {
            "task_type": "memory_embedding",
            "task_key": "memory-embedding-1",
            "queue_name": "memory",
            "payload": {"memory_id": "m1"},
            "max_retries": 1,
            "scheduled_at": "2026-11-05T14:00:00Z",
        }
        first = await client.post("/api/background-tasks", json=body)
        assert first.status_code == 201
        assert first.json()["status"] == "pending"
        duplicate = await client.post("/api/background-tasks", json=body)
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == first.json()["id"]
        changed = await client.post("/api/background-tasks", json={**body, "payload": {"memory_id": "m2"}})
        assert changed.status_code == 409

        task_id = first.json()["id"]
        skipped = await client.post(f"/api/background-tasks/{task_id}/transitions", json={"status": "completed"})
        assert skipped.status_code == 400
        queued = await client.post(f"/api/background-tasks/{task_id}/transitions", json={"status": "queued"})
        assert queued.status_code == 200
        running = await client.post(
            f"/api/background-tasks/{task_id}/transitions",
            json={"status": "running", "worker_id": "worker-1"},
        )
        assert running.status_code == 200
        retrying = await client.post(
            f"/api/background-tasks/{task_id}/transitions",
            json={"status": "failed", "error_message": "暂时失败"},
        )
        assert retrying.status_code == 200
        assert retrying.json()["status"] == "retrying"
        assert retrying.json()["retry_count"] == 1
        await client.post(f"/api/background-tasks/{task_id}/transitions", json={"status": "queued"})
        await client.post(
            f"/api/background-tasks/{task_id}/transitions",
            json={"status": "running", "worker_id": "worker-1"},
        )
        failed = await client.post(
            f"/api/background-tasks/{task_id}/transitions",
            json={"status": "failed", "error_message": "仍然失败"},
        )
        assert failed.status_code == 200
        assert failed.json()["status"] == "failed"
        assert failed.json()["retry_count"] == 2
        assert failed.json()["completed_at"] is not None
