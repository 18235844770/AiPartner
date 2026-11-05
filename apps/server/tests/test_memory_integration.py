import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.shared.database.session import dispose_engine, get_engine


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


async def test_memory_keeps_versions_and_requires_inference_evidence(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "记忆测试用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "记忆陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "记忆来源"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "我下周要出差"},
        )
        message_id = message.json()["id"]
        base = f"/api/users/{user_id}/companions/{companion_id}/memories"
        missing_evidence = await client.post(
            base,
            json={
                "memory_type": "semantic",
                "memory_category": "plan",
                "memory_origin": "ai_inference",
                "is_inference": True,
                "content": "用户下周出差",
                "change_reason": "从对话归纳",
            },
        )
        assert missing_evidence.status_code == 400
        created = await client.post(
            base,
            json={
                "memory_type": "semantic",
                "memory_category": "plan",
                "memory_origin": "ai_inference",
                "is_inference": True,
                "content": "用户下周出差",
                "change_reason": "从对话归纳",
                "sources": [
                    {
                        "source_type": "message",
                        "source_role": "evidence",
                        "message_id": message_id,
                    }
                ],
            },
        )
        assert created.status_code == 201
        body = created.json()
        memory_id = body["id"]
        assert body["current_version"]["version_number"] == 1
        assert body["sources"][0]["message_id"] == message_id
        revised = await client.post(
            f"{base}/{memory_id}/versions",
            json={
                "change_type": "supplement",
                "change_reason": "补充目的地未知",
                "content": "用户下周出差，目的地尚未说明",
            },
        )
        assert revised.status_code == 201
        assert revised.json()["current_version"]["version_number"] == 2
        assert revised.json()["id"] == memory_id
        pending = await client.post(
            f"{base}/{memory_id}/embeddings",
            json={"embedding_model": "pending-model", "status": "pending"},
        )
        assert pending.status_code == 201
        completed = await client.post(
            f"{base}/{memory_id}/embeddings",
            json={"embedding_model": "completed-model", "status": "completed", "embedding": [0.1, 0.2]},
        )
        assert completed.status_code == 201
        foreign = await client.get(f"/api/users/{uuid.uuid4()}/companions/{companion_id}/memories/{memory_id}")
        assert foreign.status_code == 404
        removed = await client.delete(f"{base}/{memory_id}")
        assert removed.status_code == 204
        gone = await client.get(f"{base}/{memory_id}")
        assert gone.status_code == 404
