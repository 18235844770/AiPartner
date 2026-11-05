import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.dialogue.api.turn_router import get_turn_service
from app.modules.dialogue.domain.context import decision_messages, final_send
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion
from app.modules.dialogue.services.turn_service import DialogueTurnService
from app.modules.model_adapter.domain.errors import ModelOutputError, ModelTimeoutError
from app.modules.model_adapter.domain.messages import TextCompletion
from app.shared.database.session import dispose_engine, get_engine


def test_decision_prompt_omits_relationship_scores_and_does_not_invent_memories() -> None:
    messages = decision_messages(
        mbti_type="INFJ",
        core_traits={"title": "内在连贯"},
        communication_preferences={"pace": "slow"},
        emotion_primary="calm",
        emotion_cause="状态初始化",
        relationship_summary="状态初始化",
        interaction_mode="available",
        proactive_allowed=False,
        recent_messages=[{"sender_type": "user", "content": "今天先这样"}],
        repair=True,
    )
    body = messages[1].content
    assert "closeness" not in body
    assert "trust" not in body
    assert "attachment" not in body
    assert '"memories": []' in body
    assert "今天先这样" in body
    assert "上一次输出不符合结构" in messages[2].content
    assert "invalid output" not in messages[2].content


def test_not_sending_becomes_quiet() -> None:
    suggestion = _suggestion(DialogueAction.RESPOND, should_send=False)
    action, should_send = final_send(suggestion)
    assert action == DialogueAction.QUIET
    assert should_send is False
    quiet, send = final_send(_suggestion(DialogueAction.QUIET, should_send=True))
    assert quiet == DialogueAction.QUIET
    assert send is False


class _Adapter:
    def __init__(self, decisions: list[object], text: str = "我在。", fail_text: bool = False) -> None:
        self._decisions = list(decisions)
        self._text = text
        self._fail_text = fail_text
        self.calls: list[tuple[str, list[object]]] = []

    async def complete_structured(self, task: object, messages: list[object], result_type: object, scope: object) -> object:
        del task, result_type, scope
        self.calls.append(("structured", messages))
        item = self._decisions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def complete_text(self, task: object, messages: list[object], scope: object, *, json_object: bool = False) -> TextCompletion:
        del task, scope, json_object
        self.calls.append(("text", messages))
        if self._fail_text:
            raise ModelTimeoutError("表达模型超时")
        return TextCompletion(
            content=self._text,
            model_name="configured-model",
            finish_reason="stop",
            input_tokens=None,
            output_tokens=None,
        )


def _suggestion(action: DialogueAction, should_send: bool, secondary: list[DialogueAction] | None = None) -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=should_send,
        primary_action=action,
        secondary_actions=secondary or [],
        motivation=DecisionMotivation(primary="回应用户当前表达"),
        topic=DecisionTopic(transition=TopicTransition.CONTINUE),
        confidence=Decimal("0.500"),
        reasoning_summary="先确定行为，再决定是否发送",
    )


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


async def _prepare(client: AsyncClient) -> SimpleNamespace:
    user = await client.post("/api/users", json={"display_name": "回合测试用户"})
    user_id = user.json()["id"]
    companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "回合陪伴"})
    companion_id = companion.json()["id"]
    conversation = await client.post(
        f"/api/users/{user_id}/companions/{companion_id}/conversations",
        json={"title": "回合会话"},
    )
    conversation_id = conversation.json()["id"]
    state = await client.post(f"/api/users/{user_id}/companions/{companion_id}/state", json={})
    assert state.status_code == 201
    persona = await client.post(
        f"/api/users/{user_id}/companions/{companion_id}/persona",
        json={"mbti_type": "INFJ"},
    )
    assert persona.status_code == 201
    return SimpleNamespace(
        user_id=user_id,
        companion_id=companion_id,
        conversation_id=conversation_id,
        turns=f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/turns",
        proactive=f"/api/users/{user_id}/companions/{companion_id}/proactive-turns",
        messages=f"/api/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages",
        state=f"/api/users/{user_id}/companions/{companion_id}/state",
    )


def _client(adapter: _Adapter) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_turn_service] = lambda: DialogueTurnService(adapter=adapter)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_quiet_does_not_generate_a_message(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.QUIET, False)])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "我先安静一会儿"})
        assert response.status_code == 201
        body = response.json()
        assert body["decision"]["primary_action"] == "quiet"
        assert body["decision"]["status"] == "completed"
        assert body["companion_message_id"] is None
        messages = await client.get(scope.messages)
        assert [item["sender_type"] for item in messages.json()] == ["user"]
    assert [name for name, _messages in adapter.calls] == ["structured"]


@pytest.mark.asyncio
async def test_respond_keeps_the_decided_action_and_uses_the_realization(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.RESPOND, True, [DialogueAction.REACT])], text="我听见了。")
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "今天有点累"})
        assert response.status_code == 201
        body = response.json()
        assert body["decision"]["primary_action"] == "respond"
        assert body["decision"]["secondary_actions"] == ["react"]
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "我听见了。"
        assert messages.json()[1]["id"] == body["companion_message_id"]
        state = await client.get(scope.state)
        assert state.json()["version"] == 1
    assert [name for name, _messages in adapter.calls] == ["structured", "text"]
    sent = adapter.calls[0][1][1].content
    assert "closeness" not in sent
    assert '"memories": []' in sent
    assert '"source": "current_message"' in sent
    assert "今天有点累" in sent


@pytest.mark.asyncio
async def test_decision_failure_uses_one_repair_then_a_plain_fallback(database_ready: None) -> None:
    adapter = _Adapter(
        [
            ModelOutputError("模型输出不符合结构"),
            ModelOutputError("模型输出不符合结构"),
        ]
    )
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "在吗"})
        assert response.status_code == 201
        assert response.json()["decision"]["primary_action"] == "respond"
        assert response.json()["decision"]["reasoning_summary"] == "决策模型不可用，改为简短回应"
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "我暂时无法完成这次回复。"
    assert [name for name, _messages in adapter.calls] == ["structured", "structured"]


@pytest.mark.asyncio
async def test_one_schema_repair_then_realization(database_ready: None) -> None:
    adapter = _Adapter(
        [ModelOutputError("模型输出不符合结构"), _suggestion(DialogueAction.ASK, True)],
        text="你想先说哪一件？",
    )
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "有两件事"})
        assert response.status_code == 201
        assert response.json()["decision"]["primary_action"] == "ask"
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "你想先说哪一件？"
    assert [name for name, _messages in adapter.calls] == ["structured", "structured", "text"]


@pytest.mark.asyncio
async def test_user_realization_failure_keeps_respond_and_uses_the_fallback_sentence(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.RESPOND, True)], fail_text=True)
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "说完了"})
        assert response.status_code == 201
        assert response.json()["decision"]["primary_action"] == "respond"
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "我暂时无法完成这次回复。"


@pytest.mark.asyncio
async def test_duplicate_client_message_calls_the_model_once(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.RESPOND, True)], text="第一次。")
    client_message_id = str(uuid.uuid4())
    async with _client(adapter) as client:
        scope = await _prepare(client)
        first = await client.post(scope.turns, json={"content": "同一句", "client_message_id": client_message_id})
        second = await client.post(scope.turns, json={"content": "同一句", "client_message_id": client_message_id})
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["decision"]["id"] == first.json()["decision"]["id"]
        messages = await client.get(scope.messages)
        assert len(messages.json()) == 2
    assert [name for name, _messages in adapter.calls] == ["structured", "text"]


@pytest.mark.asyncio
async def test_blocked_proactive_does_not_call_the_model(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.SHARE, True)])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.proactive, json={"conversation_id": scope.conversation_id})
        assert response.status_code == 201
        assert response.json()["decision"]["primary_action"] == "quiet"
        assert response.json()["decision"]["reasoning_summary"] == "当前不允许主动交流"
        assert response.json()["companion_message_id"] is None
        messages = await client.get(scope.messages)
        assert messages.json() == []
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_proactive_model_failure_stays_quiet(database_ready: None) -> None:
    adapter = _Adapter([ModelTimeoutError("决策模型超时")])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        allowed = await client.post(
            f"{scope.state}/changes",
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
        response = await client.post(scope.proactive, json={"conversation_id": scope.conversation_id})
        assert response.status_code == 201
        assert response.json()["decision"]["primary_action"] == "quiet"
        assert response.json()["companion_message_id"] is None
        assert response.json()["decision"]["reasoning_summary"] == "决策模型不可用，不主动发送"
    assert [name for name, _messages in adapter.calls] == ["structured"]


@pytest.mark.asyncio
async def test_proactive_realization_failure_does_not_send(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.SHARE, True)], fail_text=True)
    async with _client(adapter) as client:
        scope = await _prepare(client)
        allowed = await client.post(
            f"{scope.state}/changes",
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
        response = await client.post(scope.proactive, json={"conversation_id": scope.conversation_id})
        assert response.status_code == 201
        assert response.json()["decision"]["primary_action"] == "quiet"
        assert response.json()["decision"]["status"] == "completed"
        assert response.json()["companion_message_id"] is None
        messages = await client.get(scope.messages)
        assert messages.json() == []
