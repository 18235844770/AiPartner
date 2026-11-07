import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.dialogue.api.stream_schemas import TurnStarted, encode_sse
from app.modules.dialogue.api.turn_router import get_turn_service
from app.modules.dialogue.domain.context import decision_messages, final_send
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, SelfMotivation, UserNeed
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
    assert '"acquired_memories": []' in body
    assert "陪伴者" in body
    assert "Dialogue Policy" in messages[0].content
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


def test_sse_frame_names_the_event_and_keeps_data_on_one_line() -> None:
    frame = encode_sse(
        TurnStarted(
            turn_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            conversation_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            sequence=0,
        )
    )
    assert frame.startswith("id: 0\nevent: turn.started\ndata:")
    assert frame.endswith("\n\n")
    assert "\n{" not in frame


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


class _PartialStream(_Adapter):
    async def stream_text(self, task: object, messages: list[object], scope: object):
        del task, scope
        self.calls.append(("stream", messages))
        yield "半句"
        raise ModelTimeoutError("表达模型超时")


def _suggestion(action: DialogueAction, should_send: bool, secondary: list[DialogueAction] | None = None) -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=should_send,
        primary_action=action,
        secondary_actions=secondary or [],
        motivation=DecisionMotivation(primary="回应用户当前表达"),
        user_need=UserNeed(summary="用户在说当前的感受"),
        self_motivation=SelfMotivation(
            interest="没有必须接上的个人兴趣",
            viewpoint="先接住这句话",
            desire_to_express="回应，不追加问题",
        ),
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
        decisions=f"/api/users/{user_id}/companions/{companion_id}/decisions",
        state=f"/api/users/{user_id}/companions/{companion_id}/state",
    )


def _events(response: object) -> list[tuple[str, dict[str, object]]]:
    status_code = getattr(response, "status_code")
    headers = getattr(response, "headers")
    text = getattr(response, "text")
    assert status_code == 200
    assert str(headers["content-type"]).startswith("text/event-stream")
    events: list[tuple[str, dict[str, object]]] = []
    for block in str(text).split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data: dict[str, object] = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                parsed = json.loads(line.split(":", 1)[1].strip())
                assert isinstance(parsed, dict)
                data = parsed
        events.append((name, data))
    assert [int(item[1]["sequence"]) for item in events] == list(range(len(events)))
    return events


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
        events = _events(response)
        assert [name for name, _data in events] == ["turn.started", "turn.completed"]
        assert events[-1][1]["outcome"] == "quiet"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.status_code == 200
        assert decision.json()["primary_action"] == "quiet"
        assert decision.json()["status"] == "completed"
        assert decision.json()["result_message_id"] is None
        messages = await client.get(scope.messages)
        assert [item["sender_type"] for item in messages.json()] == ["user"]
        state = await client.get(scope.state)
        assert state.json()["version"] == 2
        assert state.json()["emotion"]["cause_summary"] == "这一轮选择不发消息"
        assert state.json()["motivation"]["primary"] == "rest"
        assert state.json()["interaction"]["last_companion_message_at"] is None
        assert state.json()["relationship"]["closeness"] == 0
    assert [name for name, _messages in adapter.calls] == ["structured"]


@pytest.mark.asyncio
async def test_respond_keeps_the_decided_action_and_uses_the_realization(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.RESPOND, True, [DialogueAction.REACT])], text="我听见了。")
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "今天有点累"})
        events = _events(response)
        assert [name for name, _data in events] == [
            "turn.started",
            "message.started",
            "message.delta",
            "message.completed",
            "turn.completed",
        ]
        assert events[-1][1]["outcome"] == "replied"
        assert events[2][1]["delta"] == "我听见了。"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "respond"
        assert decision.json()["secondary_actions"] == ["react"]
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "我听见了。"
        assert messages.json()[1]["status"] == "completed"
        assert messages.json()[1]["id"] == events[1][1]["message_id"]
        state = await client.get(scope.state)
        body = state.json()
        assert body["version"] == 2
        assert body["emotion"]["primary"] == "attentive"
        assert body["emotion"]["cause_summary"] == "这一轮在听用户说话"
        assert body["motivation"]["primary"] == "listen"
        assert body["motivation"]["secondary"] == ["connect"]
        assert body["interaction"]["waiting_for_user"] is True
        assert body["interaction"]["consecutive_unanswered_messages"] == 1
        assert body["interaction"]["last_user_response_at"] is not None
        assert body["interaction"]["last_companion_message_at"] is not None
        assert body["interaction"]["proactive_allowed"] is False
        assert body["relationship"]["closeness"] == 0
        assert body["relationship"]["summary"] == "已经开始交流，关系程度仍保持原来的判断"
        events_response = await client.get(f"{scope.state}/events")
        assert events_response.status_code == 200
        recorded = [item for item in events_response.json() if item["source_type"] == "dialogue_decision"]
        assert len(recorded) == 1
        assert recorded[0]["dialogue_decision_id"] == events[0][1]["turn_id"]
    assert [name for name, _messages in adapter.calls] == ["structured", "text"]
    sent = adapter.calls[0][1][1].content
    assert "closeness" not in sent
    assert '"acquired_memories": []' in sent
    assert "陪伴者" in sent
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
        events = _events(response)
        assert events[-1][1]["outcome"] == "replied"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "respond"
        assert decision.json()["reasoning_summary"] == "决策模型不可用，改为简短回应"
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
        events = _events(response)
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "ask"
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "你想先说哪一件？"
    assert [name for name, _messages in adapter.calls] == ["structured", "structured", "text"]


@pytest.mark.asyncio
async def test_user_realization_failure_keeps_respond_and_uses_the_fallback_sentence(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.RESPOND, True)], fail_text=True)
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "说完了"})
        events = _events(response)
        assert "message.completed" in [name for name, _data in events]
        assert events[-1][1]["outcome"] == "replied"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "respond"
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
        first_events = _events(first)
        second_events = _events(second)
        assert second_events[0][1]["turn_id"] == first_events[0][1]["turn_id"]
        assert second_events[-1][1]["outcome"] == "replied"
        messages = await client.get(scope.messages)
        assert len(messages.json()) == 2
    assert [name for name, _messages in adapter.calls] == ["structured", "text"]


@pytest.mark.asyncio
async def test_blocked_proactive_does_not_call_the_model(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.SHARE, True)])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.proactive, json={"conversation_id": scope.conversation_id})
        events = _events(response)
        assert [name for name, _data in events] == ["turn.started", "turn.completed"]
        assert events[-1][1]["outcome"] == "quiet"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "quiet"
        assert decision.json()["reasoning_summary"] == "当前不允许主动交流"
        assert decision.json()["result_message_id"] is None
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
        events = _events(response)
        assert [name for name, _data in events] == ["turn.started", "turn.completed"]
        assert events[-1][1]["outcome"] == "quiet"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "quiet"
        assert decision.json()["result_message_id"] is None
        assert decision.json()["reasoning_summary"] == "决策模型不可用，不主动发送"
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
        events = _events(response)
        assert [name for name, _data in events] == ["turn.started", "turn.completed"]
        assert events[-1][1]["outcome"] == "quiet"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["primary_action"] == "quiet"
        assert decision.json()["status"] == "completed"
        assert decision.json()["result_message_id"] is None
        messages = await client.get(scope.messages)
        assert messages.json() == []


@pytest.mark.asyncio
async def test_partial_realization_failure_does_not_complete_the_message(database_ready: None) -> None:
    adapter = _PartialStream([_suggestion(DialogueAction.RESPOND, True)])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        response = await client.post(scope.turns, json={"content": "说到一半"})
        events = _events(response)
        names = [name for name, _data in events]
        assert "message.delta" in names
        assert "message.completed" not in names
        assert names[-1] == "turn.failed"
        assert events[-1][1]["error"] == {
            "code": "MODEL_TIMEOUT",
            "message": "模型服务暂时不可用",
            "retryable": True,
        }
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["status"] == "failed"
        messages = await client.get(scope.messages)
        assert messages.json()[1]["content"] == "半句"
        assert messages.json()[1]["status"] == "failed"
        assert messages.json()[1]["id"] == events[1][1]["message_id"]


async def _allow_proactive(client: AsyncClient, state_url: str) -> None:
    allowed = await client.post(
        f"{state_url}/changes",
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


@pytest.mark.asyncio
async def test_proactive_reply_streams_one_message(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.SHARE, True)], text="我来找你。")
    async with _client(adapter) as client:
        scope = await _prepare(client)
        await _allow_proactive(client, scope.state)
        response = await client.post(scope.proactive, json={"conversation_id": scope.conversation_id})
        events = _events(response)
        assert [name for name, _data in events] == [
            "turn.started",
            "message.started",
            "message.delta",
            "message.completed",
            "turn.completed",
        ]
        assert events[2][1]["delta"] == "我来找你。"
        assert events[-1][1]["outcome"] == "replied"
        messages = await client.get(scope.messages)
        assert len(messages.json()) == 1
        assert messages.json()[0]["sender_type"] == "companion"
        assert messages.json()[0]["status"] == "completed"
        assert messages.json()[0]["id"] == events[1][1]["message_id"]
    assert [name for name, _messages in adapter.calls] == ["structured", "text"]


@pytest.mark.asyncio
async def test_partial_proactive_failure_does_not_complete_the_message(database_ready: None) -> None:
    adapter = _PartialStream([_suggestion(DialogueAction.SHARE, True)])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        await _allow_proactive(client, scope.state)
        response = await client.post(scope.proactive, json={"conversation_id": scope.conversation_id})
        events = _events(response)
        names = [name for name, _data in events]
        assert "message.completed" not in names
        assert names[-1] == "turn.failed"
        decision = await client.get(f"{scope.decisions}/{events[0][1]['turn_id']}")
        assert decision.json()["status"] == "failed"
        messages = await client.get(scope.messages)
        assert messages.json()[0]["content"] == "半句"
        assert messages.json()[0]["status"] == "failed"

