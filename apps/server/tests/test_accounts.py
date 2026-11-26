import asyncio
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config.settings import get_settings
from app.main import MOBILE_DIST, create_app
from app.modules.conversation.api.account_router import _chat_frames, audio
from app.modules.conversation.repositories.models import ChatTurn, Conversation, Message
from app.modules.conversation.services.account_chat import AccountChatService
from app.modules.dialogue.api.stream_schemas import TurnCompleted
from app.modules.dialogue.domain.suggestion import user_fallback
from app.modules.dialogue.services.turn_service import DecisionModel, DialogueTurnService
from app.modules.memory.services.retrieval import MemoryRetrievalService
from app.modules.model_adapter.domain.errors import ModelTimeoutError
from app.modules.model_adapter.domain.messages import TextCompletion
from app.modules.identity.api.account_router import ACCESS_COOKIE, REFRESH_COOKIE
from app.modules.identity.repositories.models import AuthSession, Companion, User
from app.modules.identity.services.auth_service import token_hash
from app.modules.identity.services.account_erasure import AccountErasureService
from app.shared.database.session import dispose_engine, get_session_factory
from app.shared.exceptions.errors import UnavailableError


MUTATION_HEADERS = {"X-Companion-Request": "1"}


@pytest.fixture
async def account_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("ACCOUNT_MODE", "true")
    get_settings.cache_clear()
    await dispose_engine()
    try:
        transport = ASGITransport(app=create_app(), client=(f"test-{uuid.uuid4().hex}", 1234))
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            yield client
    finally:
        await dispose_engine()
        get_settings.cache_clear()


async def test_account_mode_requires_auth_and_hides_local_routes(account_client: AsyncClient) -> None:
    assert (await account_client.get("/api/user/me")).status_code == 401
    assert (await account_client.get("/api/companion/me")).status_code == 401
    assert (await account_client.get("/api/chat/messages")).status_code == 401
    assert (await account_client.get("/api/chat/stream")).status_code == 401
    assert (await account_client.get("/api/companion/persona")).status_code == 401
    assert (await account_client.get("/api/companion/voice/presets")).status_code == 401
    assert (await account_client.post("/api/users", json={"display_name": "访客"})).status_code == 404
    assert (await account_client.post("/api/auth/logout")).status_code == 403
    assert (await account_client.post(
        "/api/auth/logout", headers={**MUTATION_HEADERS, "Sec-Fetch-Site": "cross-site"},
    )).status_code == 403
    mobile = await account_client.get("/mobile/")
    if (MOBILE_DIST / "index.html").is_file():
        assert mobile.status_code == 200
        assert 'id="app"' in mobile.text
        bundle = re.search(r'src="(/mobile/assets/[^\"]+\.js)"', mobile.text)
        assert bundle is not None
        assert (await account_client.get(bundle.group(1))).status_code == 200
    else:
        assert mobile.status_code == 503


async def test_account_validation_does_not_return_credentials(account_client: AsyncClient) -> None:
    response = await account_client.post(
        "/api/auth/register", headers=MUTATION_HEADERS,
        json={"username": "short-password", "password": "secret", "unknown_token": "private"},
    )
    assert response.status_code == 422
    assert "secret" not in response.text
    assert "private" not in response.text

    response = await account_client.post(
        "/api/auth/register", headers=MUTATION_HEADERS,
        json={"username": "password-mismatch", "password": "first-secret", "confirm_password": "second-secret"},
    )
    assert response.status_code == 422
    assert "first-secret" not in response.text
    assert "second-secret" not in response.text


@pytest.mark.skipif(not os.environ.get("ACCOUNT_INTEGRATION_TESTS"), reason="requires migrated PostgreSQL and Redis")
async def test_real_account_sessions_and_isolated_initialization(account_client: AsyncClient) -> None:
    transport = account_client._transport
    original_password = "account-test-password"
    username = f"test_{uuid.uuid4().hex}"
    credentials = {"username": username.upper(), "password": original_password}
    form = {**credentials, "confirm_password": original_password, "timezone": "Asia/Shanghai"}
    async with AsyncClient(transport=transport, base_url="https://test") as other_device, AsyncClient(
        transport=transport, base_url="https://test",
    ) as other_account:
        registered = await asyncio.gather(*(
            client.post("/api/auth/register", json=form, headers=MUTATION_HEADERS)
            for client in (account_client, other_device)
        ))
        assert all(response.status_code == 202 for response in registered)
        assert (await other_account.post(
            "/api/auth/register", json={**form, "username": f"test_{uuid.uuid4().hex}"}, headers=MUTATION_HEADERS,
        )).status_code == 202
        login = await account_client.post("/api/auth/login", json=credentials, headers=MUTATION_HEADERS)
        assert login.status_code == 204
        assert all("HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
                   for cookie in login.headers.get_list("set-cookie"))
        assert (await other_device.post("/api/auth/login", json=credentials, headers=MUTATION_HEADERS)).status_code == 204
        first = (await account_client.get("/api/companion/me")).json()
        second = (await other_device.get("/api/companion/me")).json()
        assert first == second
        assert first["initialization_status"] == "ready"
        assert (await other_account.get("/api/companion/me")).status_code == 401

        stale_refresh = account_client.cookies.get(REFRESH_COOKIE)
        stale_access = account_client.cookies.get(ACCESS_COOKIE)
        assert (await account_client.post("/api/auth/refresh", headers=MUTATION_HEADERS)).status_code == 204
        assert (await other_account.post(
            "/api/auth/refresh", headers={**MUTATION_HEADERS, "Cookie": f"{REFRESH_COOKIE}={stale_refresh}"},
        )).status_code == 401
        assert (await other_account.get(
            "/api/user/me", headers={"Cookie": f"{ACCESS_COOKIE}={stale_access}"},
        )).status_code == 401

        assert (await account_client.post(
            "/api/user/password", headers=MUTATION_HEADERS,
            json={"current_password": original_password, "new_password": "new-account-test-password"},
        )).status_code == 204
        assert (await other_device.get("/api/user/me")).status_code == 401
        assert (await account_client.get("/api/user/me")).json()["username"] == username

        async with get_session_factory()() as session:
            user = await session.scalar(select(User).where(User.username == username))
            assert user is not None and user.password_hash.startswith("$argon2id$")
            ids = list(await session.scalars(select(Companion.id).where(Companion.owner_user_id == user.id)))
            assert ids == [uuid.UUID(first["id"])]
            device = await session.scalar(select(AuthSession).where(
                AuthSession.access_token_hash == token_hash(account_client.cookies.get(ACCESS_COOKIE)),
            ))
            assert device is not None
            assert device.refresh_token_hash == token_hash(account_client.cookies.get(REFRESH_COOKIE))

        assert (await account_client.post("/api/auth/logout", headers=MUTATION_HEADERS)).status_code == 204
        assert (await account_client.get("/api/user/me")).status_code == 401


@pytest.mark.skipif(not os.environ.get("ACCOUNT_INTEGRATION_TESTS"), reason="requires migrated PostgreSQL and Redis")
async def test_account_chat_recovers_and_erases_only_its_own_data(
    account_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = {"username": f"test_{uuid.uuid4().hex}", "password": "account-test-password"}
    other_credentials = {**credentials, "username": f"test_{uuid.uuid4().hex}"}
    async with AsyncClient(transport=account_client._transport, base_url="https://test") as other:
        for client, login in ((account_client, credentials), (other, other_credentials)):
            assert (await client.post(
                "/api/auth/register", json={**login, "confirm_password": login["password"]}, headers=MUTATION_HEADERS,
            )).status_code == 202
            assert (await client.post("/api/auth/login", json=login, headers=MUTATION_HEADERS)).status_code == 204

        user_id = uuid.UUID((await account_client.get("/api/user/me")).json()["id"])
        companion_id = uuid.UUID((await account_client.get("/api/companion/me")).json()["id"])
        other_companion_id = uuid.UUID((await other.get("/api/companion/me")).json()["id"])
        assert other_companion_id != companion_id
        stale_headers = {**MUTATION_HEADERS, "X-Companion-Account": str(user_id)}
        assert (await other.get("/api/chat/messages", headers=stale_headers)).status_code == 401
        assert (await other.post("/api/auth/logout", headers=stale_headers)).status_code == 401
        assert (await other.get("/api/user/me")).status_code == 200
        assert (await account_client.get("/api/companion/persona", headers=stale_headers)).status_code == 200
        assert (await account_client.get("/api/companion/voice/preset", headers=stale_headers)).status_code == 200
        initial_persona = (await account_client.get("/api/companion/persona")).json()["current_version"]
        next_mbti = "ENFP" if initial_persona["mbti_type"] != "ENFP" else "INFP"
        saved = await account_client.patch(
            "/api/companion/me", json={"name": "本账号伴侣", "description": "仅本人可看", "mbti_type": next_mbti},
            headers=stale_headers,
        )
        assert saved.status_code == 200 and saved.json()["name"] == "本账号伴侣"
        updated = (await account_client.get("/api/companion/persona")).json()["current_version"]
        assert updated["mbti_type"] == next_mbti
        assert updated["version_number"] == initial_persona["version_number"] + 1
        assert (await other.get("/api/companion/me")).json()["name"] != "本账号伴侣"

        first_body = {"client_message_id": str(uuid.uuid4()), "content": "账号 A 的消息"}
        repeated = await asyncio.gather(*(
            account_client.post("/api/chat/messages", json=first_body, headers=MUTATION_HEADERS) for _ in range(2)
        ))
        assert all(response.status_code == 202 for response in repeated)
        first = repeated[0].json()
        assert repeated[1].json() == first
        assert (await account_client.post(
            "/api/chat/messages", json={**first_body, "content": "同一发送标识，不同内容"}, headers=MUTATION_HEADERS,
        )).status_code == 409
        second = await account_client.post(
            "/api/chat/messages", json={**first_body, "client_message_id": str(uuid.uuid4())}, headers=MUTATION_HEADERS,
        )
        assert second.status_code == 202
        assert (await other.get("/api/chat/messages")).json()["messages"] == []
        assert (await other.post(f"/api/chat/turns/{first['turn_id']}/retry", headers=MUTATION_HEADERS)).status_code == 404
        assert (await other.get(f"/api/chat/audio/{first['message']['id']}")).status_code == 404

        history = (await account_client.get("/api/chat/messages?limit=1")).json()
        assert history["has_more"] and history["messages"][0]["sequence_number"] == 2
        before = (await account_client.get(f"/api/chat/messages?before_sequence={history['next_cursor']}")).json()
        assert [message["sequence_number"] for message in before["messages"]] == [1]

        adapter = MagicMock(spec=DecisionModel)
        adapter.complete_structured = AsyncMock(side_effect=ModelTimeoutError("模型测试超时"))
        retrieval = MagicMock(spec=MemoryRetrievalService)
        retrieval.retrieve = AsyncMock(return_value=[])
        await AccountChatService(DialogueTurnService(adapter=adapter, retrieval=retrieval)).process_one(user_id, companion_id)
        adapter.complete_structured.assert_awaited_once()
        retried = await account_client.post(f"/api/chat/turns/{first['turn_id']}/retry", headers=MUTATION_HEADERS)
        assert retried.status_code == 202 and retried.json()["attempt"] == 2

        async def quiet(*args, managed_decision_id, **kwargs):
            yield TurnCompleted(turn_id=managed_decision_id, outcome="quiet", sequence=1)

        engine = MagicMock(spec=DialogueTurnService)
        engine.iter_user_turn.side_effect = quiet
        await AccountChatService(engine).process_one(user_id, companion_id)
        access = account_client.cookies.get(ACCESS_COOKIE)
        async with aclosing(_chat_frames(user_id, companion_id, 0, access)) as stream:
            first_frame = await anext(stream)
            second_frame = await anext(stream)
            status_frame = await anext(stream)
            assert first_frame.startswith("id: message:1\n")
            assert second_frame.startswith("id: message:2\n")
            assert '"status":"quiet"' in status_frame
        page = (await account_client.get("/api/chat/messages")).json()
        assert len(page["messages"]) == 2

        adapter.complete_structured.side_effect = None
        adapter.complete_structured.return_value = user_fallback()
        adapter.complete_text.return_value = TextCompletion(
            content="我在。", model_name="test", finish_reason="stop", input_tokens=None, output_tokens=None,
        )
        await AccountChatService(DialogueTurnService(adapter=adapter, retrieval=retrieval)).process_one(user_id, companion_id)
        completed = (await account_client.get("/api/chat/messages?after_sequence=2")).json()["messages"]
        assert len(completed) == 1 and completed[0]["status"] == "completed"
        assert completed[0]["turn_id"] == second.json()["turn_id"]
        assert completed[0]["audio_url"] is None
        monkeypatch.setattr(audio, "synthesize_for_message", AsyncMock(side_effect=UnavailableError("音频不可用")))
        tts = await account_client.post(f"/api/chat/messages/{completed[0]['id']}/audio", headers=MUTATION_HEADERS)
        assert tts.status_code == 503
        assert (await account_client.get("/api/chat/messages?after_sequence=2")).json()["messages"] == completed

        deleted = await account_client.request(
            "DELETE", "/api/user/me", json={"password": credentials["password"]}, headers=MUTATION_HEADERS,
        )
        assert deleted.status_code == 202
        assert (await account_client.get("/api/user/me", headers={"Cookie": f"{ACCESS_COOKIE}={access}"})).status_code == 401
        await AccountErasureService().process(user_id)
        async with get_session_factory()() as session:
            assert await session.get(User, user_id) is None
            assert await session.get(Companion, companion_id) is None
            assert await session.get(Conversation, uuid.UUID(first["message"]["conversation_id"])) is None
            assert await session.get(Message, uuid.UUID(first["message"]["id"])) is None
            assert await session.get(ChatTurn, uuid.UUID(first["turn_id"])) is None
            assert await session.get(Companion, other_companion_id) is not None
        assert (await other.get("/api/companion/me")).status_code == 200
