import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from app.config.settings import get_settings
from app.main import create_app
from app.modules.infrastructure.worker import embed_memory_task
from app.modules.memory.api.schemas import RecordEmbeddingRequest
from app.modules.memory.domain.enums import EmbeddingStatus
from app.modules.memory.services.embedding import MemoryEmbeddingService
from app.modules.model_adapter.domain.embedding import EMBEDDING_DIMENSIONS, EmbeddingResult
from app.modules.model_adapter.domain.errors import ModelTimeoutError
from app.modules.model_adapter.services.model_adapter import ModelCallScope
from app.shared.database.session import dispose_engine, get_engine, get_session_factory
from tests.model_config_parking import park_model_config, restore_model_config


class _Vectors:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def embed(self, task: object, texts: list[str], scope: ModelCallScope) -> EmbeddingResult:
        del task, scope
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert texts
        return EmbeddingResult(
            model_name=get_settings().embedding_model_name,
            vectors=[[0.02] * EMBEDDING_DIMENSIONS],
        )


def test_completed_embedding_must_have_1024_values() -> None:
    with pytest.raises(ValidationError):
        RecordEmbeddingRequest(embedding_model="local", status=EmbeddingStatus.COMPLETED, embedding=[0.1, 0.2])


async def test_embedding_handler_rejects_a_bad_payload() -> None:
    task = SimpleNamespace(id=uuid.uuid4(), companion_id=uuid.uuid4(), payload={"user_id": "not-a-uuid"})
    with pytest.raises(ValueError):
        await embed_memory_task(None, task)


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


async def test_embedding_task_stores_a_vector_and_keeps_the_memory_when_it_fails(database_ready: None) -> None:
    parked = await park_model_config("embedding_model")
    await _remove_embedding_config()
    vectors = _Vectors()
    failing = _Vectors(ModelTimeoutError("模型调用超时"))
    service = MemoryEmbeddingService(adapter=vectors)
    try:
        user_id, companion_id, memory_id, version_id = await _create_memory("用户下周出差")
        task_key = f"memory-embedding:{version_id}"
        assert await _task_count(task_key) == 1
        task = _task(user_id, companion_id, memory_id, version_id)
        async with get_session_factory()() as session:
            async with session.begin():
                stored = await embed_memory_task(session, task, service)
        assert stored == {"status": "completed", "memory_id": memory_id, "skipped": False}
        assert vectors.calls == 1
        assert await _embedding_status(version_id) == "completed"
        assert await _embedding_config() == ("local", get_settings().embedding_model_name)
        async with get_session_factory()() as session:
            async with session.begin():
                again = await embed_memory_task(session, task, service)
        assert again["skipped"] is True
        assert vectors.calls == 1

        failed_user, failed_companion, failed_memory, failed_version = await _create_memory("用户喜欢喝茶")
        failed_service = MemoryEmbeddingService(adapter=failing)
        async with get_session_factory()() as session:
            async with session.begin():
                with pytest.raises(ModelTimeoutError):
                    await failed_service.embed_version(
                        session,
                        user_id=uuid.UUID(failed_user),
                        companion_id=uuid.UUID(failed_companion),
                        memory_id=uuid.UUID(failed_memory),
                        version_id=uuid.UUID(failed_version),
                        task_id=uuid.uuid4(),
                    )
        assert await _embedding_status(failed_version) == "failed"
        assert await _memory_exists(failed_user, failed_companion, failed_memory)
    finally:
        await _remove_embedding_config()
        await restore_model_config(*parked)


async def _create_memory(content: str) -> tuple[str, str, str, str]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "向量测试用户"})
        assert user.status_code == 201
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "向量陪伴"})
        assert companion.status_code == 201
        companion_id = companion.json()["id"]
        created = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "plan",
                "memory_origin": "user_explicit",
                "content": content,
                "change_reason": "用户明确说明",
            },
        )
        assert created.status_code == 201
        body = created.json()
        return user_id, companion_id, body["id"], body["current_version_id"]


def _task(user_id: str, companion_id: str, memory_id: str, version_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        companion_id=uuid.UUID(companion_id),
        payload={"user_id": user_id, "memory_id": memory_id, "version_id": version_id},
    )


async def _task_count(task_key: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM background_tasks WHERE task_key = :task_key"),
            {"task_key": task_key},
        )
    return int(count or 0)


async def _embedding_status(version_id: str) -> str:
    async with get_engine().connect() as connection:
        status = await connection.scalar(
            text("SELECT status FROM memory_embeddings WHERE memory_version_id = :version_id"),
            {"version_id": version_id},
        )
    assert isinstance(status, str)
    return status


async def _embedding_config() -> tuple[str, str]:
    async with get_engine().connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT provider, model_name
                    FROM model_configs
                    WHERE config_key = 'embedding_model' AND is_default IS TRUE
                    """
                )
            )
        ).one()
    return str(row.provider), str(row.model_name)


async def _memory_exists(user_id: str, companion_id: str, memory_id: str) -> bool:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        loaded = await client.get(f"/api/users/{user_id}/companions/{companion_id}/memories/{memory_id}")
    return loaded.status_code == 200


async def _remove_embedding_config() -> None:
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                DELETE FROM model_call_logs
                WHERE config_id IN (SELECT id FROM model_configs WHERE config_key = 'embedding_model')
                """
            )
        )
        await connection.execute(text("DELETE FROM model_configs WHERE config_key = 'embedding_model'"))
