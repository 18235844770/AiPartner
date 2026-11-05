import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


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
        # 每个测试使用独立事件循环，连接池不能带到下一次。
        await dispose_engine()


async def test_duplicate_active_default_companion_is_rejected(database_ready: None) -> None:
    factory = get_session_factory()
    user_id = uuid.uuid4()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    async with factory() as session:
        await _insert_user(session, user_id)
        await _insert_default_companion(session, first_id, user_id)
        await session.commit()
    async with factory() as session:
        with pytest.raises(IntegrityError):
            await _insert_default_companion(session, second_id, user_id)
            await session.commit()
        await session.rollback()
    await _cleanup(user_id)


async def test_message_sequence_and_idempotency(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "集成测试用户"})
        assert user.status_code == 201
        user_id = user.json()["id"]
        companion = await client.post(
            f"/api/users/{user_id}/companions",
            json={"name": "测试陪伴", "is_default": True},
        )
        assert companion.status_code == 201
        companion_id = companion.json()["id"]
        created = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "第一次见面"},
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]
        client_message_id = str(uuid.uuid4())
        base = (
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages"
        )
        first = await client.post(
            base,
            json={"sender_type": "user", "content": "你好", "client_message_id": client_message_id},
        )
        second = await client.post(
            base,
            json={"sender_type": "user", "content": "你好", "client_message_id": client_message_id},
        )
        third = await client.post(base, json={"sender_type": "companion", "content": "我在"})
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        assert third.status_code == 201
        assert third.json()["sequence_number"] == 2
        listed = await client.get(base)
        assert [item["sequence_number"] for item in listed.json()] == [1, 2]
        foreign = await client.get(
            f"/api/users/{uuid.uuid4()}/companions/{companion_id}/conversations/{conversation_id}/messages"
        )
        assert foreign.status_code == 404
    await _cleanup(uuid.UUID(user_id))


async def _insert_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        text(
            """
            INSERT INTO users (id, display_name, timezone, locale, status)
            VALUES (:id, :display_name, 'UTC', 'zh-CN', 'active')
            """
        ),
        {"id": user_id, "display_name": f"约束测试 {user_id.hex[:8]}"},
    )


async def _insert_default_companion(session: AsyncSession, companion_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(
        text(
            """
            INSERT INTO companions (id, owner_user_id, name, status, is_default)
            VALUES (:id, :owner_user_id, '默认', 'active', true)
            """
        ),
        {"id": companion_id, "owner_user_id": user_id},
    )


async def _cleanup(user_id: uuid.UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                DELETE FROM messages
                WHERE conversation_id IN (
                    SELECT id FROM conversations WHERE user_id = :user_id
                )
                """
            ),
            {"user_id": user_id},
        )
        await session.execute(text("DELETE FROM conversations WHERE user_id = :user_id"), {"user_id": user_id})
        await session.execute(text("DELETE FROM companions WHERE owner_user_id = :user_id"), {"user_id": user_id})
        await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        await session.commit()
