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


async def test_state_snapshot_and_event_share_one_version(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "状态测试用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "状态陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "状态来源"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "我先安静一会儿"},
        )
        message_id = message.json()["id"]
        base = f"/api/users/{user_id}/companions/{companion_id}/state"

        missing = await client.get(base)
        assert missing.status_code == 404

        created = await client.post(base, json={})
        assert created.status_code == 201
        body = created.json()
        assert body["version"] == 1
        assert body["emotion"]["primary"] == "calm"
        assert body["relationship"]["closeness"] == 0
        assert body["interaction"]["proactive_allowed"] is False
        assert body["interaction"]["energy"] == "normal"
        assert body["motivation"]["primary"] == "rest"

        again = await client.post(base, json={})
        assert again.status_code == 409

        stale = await client.post(
            f"{base}/changes",
            json={
                "expected_version": 0,
                "source_type": "system",
                "reason": "版本过旧",
                "interaction": {
                    "mode": "quiet",
                    "proactive_allowed": False,
                    "waiting_for_user": False,
                    "consecutive_unanswered_messages": 0,
                },
            },
        )
        assert stale.status_code == 422

        unchanged = await client.post(
            f"{base}/changes",
            json={
                "expected_version": 1,
                "source_type": "system",
                "reason": "没有实际变化",
                "motivation": {
                    "primary": "rest",
                    "secondary": [],
                    "intensity": 0,
                    "reason": "状态初始化",
                },
            },
        )
        assert unchanged.status_code == 400

        updated = await client.post(
            f"{base}/changes",
            json={
                "expected_version": 1,
                "source_type": "user_message",
                "reason": "用户要求先安静",
                "message_id": message_id,
                "interaction": {
                    "mode": "quiet",
                    "proactive_allowed": False,
                    "waiting_for_user": False,
                    "consecutive_unanswered_messages": 0,
                },
            },
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2
        assert updated.json()["interaction"]["mode"] == "quiet"
        assert updated.json()["emotion"]["primary"] == "calm"

        conflict = await client.post(
            f"{base}/changes",
            json={
                "expected_version": 1,
                "source_type": "system",
                "reason": "使用旧版本",
                "emotion": {
                    "primary": "calm",
                    "secondary": [],
                    "intensity": 0.2,
                    "valence": 0,
                    "arousal": 0,
                    "cause_summary": "重复提交",
                },
            },
        )
        assert conflict.status_code == 409

        events = await client.get(f"{base}/events")
        assert events.status_code == 200
        payloads = events.json()
        assert [item["event_type"] for item in payloads] == ["state_initialized", "interaction_changed"]
        assert payloads[0]["version_before"] is None
        assert payloads[0]["version_after"] == 1
        assert payloads[1]["version_before"] == 1
        assert payloads[1]["version_after"] == 2
        assert payloads[1]["message_id"] == message_id
        assert payloads[1]["conversation_id"] == conversation_id
        assert payloads[1]["source_type"] == "user_message"

        outsider = await client.post("/api/users", json={"display_name": "其他用户"})
        foreign = await client.get(f"/api/users/{outsider.json()['id']}/companions/{companion_id}/state")
        assert foreign.status_code == 404


async def test_state_change_requires_a_reason_and_a_dimension(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "状态校验用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "校验陪伴"})
        base = f"/api/users/{user_id}/companions/{companion.json()['id']}/state"
        created = await client.post(base, json={})
        assert created.status_code == 201
        missing_dimension = await client.post(
            f"{base}/changes",
            json={"expected_version": 1, "source_type": "system", "reason": "没有维度"},
        )
        assert missing_dimension.status_code == 422
        blank_reason = await client.post(
            f"{base}/changes",
            json={
                "expected_version": 1,
                "source_type": "system",
                "reason": "  ",
                "interaction": {
                    "mode": "paused",
                    "proactive_allowed": False,
                    "waiting_for_user": False,
                    "consecutive_unanswered_messages": 0,
                },
            },
        )
        assert blank_reason.status_code == 422
