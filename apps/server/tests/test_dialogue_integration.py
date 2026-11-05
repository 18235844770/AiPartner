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


def _decision(
    trigger_type: str,
    action: str,
    message_id: str | None = None,
    secondary: list[str] | None = None,
    conversation_id: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "trigger_type": trigger_type,
        "primary_action": action,
        "secondary_actions": secondary or [],
        "motivation": {"primary": "回应用户当前表达"},
        "topic": {"transition": "continue"},
        "confidence": "0.800",
        "reasoning_summary": "先确定行为，再决定是否发送",
    }
    if message_id is not None:
        body["trigger_message_id"] = message_id
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return body


async def test_quiet_is_recorded_without_a_message_and_realization_keeps_the_action(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "决策测试用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "决策陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "决策会话"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
            json={"sender_type": "user", "content": "我今天先这样"},
        )
        message_id = message.json()["id"]
        decisions = f"/api/users/{user_id}/companions/{companion_id}/decisions"
        state = f"/api/users/{user_id}/companions/{companion_id}/state"

        before_state = await client.post(decisions, json=_decision("user_message", "quiet", message_id))
        assert before_state.status_code == 404

        created_state = await client.post(state, json={})
        assert created_state.status_code == 201

        blocked = await client.post(
            decisions,
            json=_decision("proactive", "share", conversation_id=conversation_id),
        )
        assert blocked.status_code == 400
        assert blocked.json()["message"] == "当前不允许主动交流"

        paired = await client.post(decisions, json=_decision("user_message", "quiet", message_id, ["ask"]))
        assert paired.status_code == 422

        quiet = await client.post(decisions, json=_decision("user_message", "quiet", message_id))
        assert quiet.status_code == 201
        assert quiet.json()["status"] == "completed"
        assert quiet.json()["result_message_id"] is None
        assert quiet.json()["primary_action"] == "quiet"
        quiet_reply = await client.post(
            f"{decisions}/{quiet.json()['id']}/realization",
            json={"content": "这句话不应该发出去"},
        )
        assert quiet_reply.status_code == 400

        allowed = await client.post(
            f"{state}/changes",
            json={
                "expected_version": 1,
                "source_type": "system",
                "reason": "调试中允许主动交流",
                "interaction": {
                    "mode": "available",
                    "proactive_allowed": True,
                    "waiting_for_user": False,
                    "consecutive_unanswered_messages": 0,
                },
            },
        )
        assert allowed.status_code == 200

        recorded = await client.post(
            decisions,
            json=_decision("user_message", "respond", message_id, ["react"]),
        )
        assert recorded.status_code == 201
        assert recorded.json()["status"] == "approved"
        assert recorded.json()["secondary_actions"] == ["react"]
        decision_id = recorded.json()["id"]

        realized = await client.post(
            f"{decisions}/{decision_id}/realization",
            json={"content": "听到了，今天先到这里。"},
        )
        assert realized.status_code == 200
        assert realized.json()["status"] == "completed"
        assert realized.json()["primary_action"] == "respond"
        assert realized.json()["result_message_id"] is not None

        repeated = await client.post(
            f"{decisions}/{decision_id}/realization",
            json={"content": "再发一次"},
        )
        assert repeated.status_code == 409

        messages = await client.get(
            f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages"
        )
        senders = [item["sender_type"] for item in messages.json()]
        assert senders == ["user", "companion"]

        proactive = await client.post(
            decisions,
            json=_decision("proactive", "share", conversation_id=conversation_id),
        )
        assert proactive.status_code == 201
        assert proactive.json()["status"] == "approved"
        assert proactive.json()["conversation_id"] == conversation_id

        outsider = await client.post("/api/users", json={"display_name": "其他用户"})
        foreign = await client.get(f"/api/users/{outsider.json()['id']}/companions/{companion_id}/decisions")
        assert foreign.status_code == 404
