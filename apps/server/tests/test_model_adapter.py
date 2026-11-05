import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import text

from app.config.settings import Settings
from app.main import create_app
from app.modules.infrastructure.domain.enums import ModelCallStatus, ModelConfigKey
from app.modules.model_adapter.domain.errors import ModelCapabilityError, ModelHttpError, ModelOutputError, ModelTimeoutError
from app.modules.model_adapter.domain.messages import ChatMessage, build_chat_payload
from app.modules.model_adapter.services.deepseek_client import DeepSeekHttpClient, parse_sse_data_line
from app.modules.model_adapter.services.model_adapter import ModelAdapter, ModelCallScope
from app.shared.database.session import dispose_engine, get_engine, get_session_factory
from tests.model_config_parking import park_model_config, restore_model_config


class _Probe(BaseModel):
    primary_action: str


class _Session:
    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    def begin(self) -> "_Session":
        return self


class _Logs:
    def __init__(self) -> None:
        self.records: list[object] = []

    async def record(self, session: object, data: object) -> object:
        del session
        self.records.append(data)
        return data


class _Configs:
    def __init__(self, config: object) -> None:
        self.config = config

    async def get_default(self, session: object, task_type: str) -> object:
        del session, task_type
        return self.config


class _Client:
    def __init__(self, results: list[object] | None = None, chunks: list[dict[str, object]] | None = None) -> None:
        self.payloads: list[dict[str, object]] = []
        self._results = list(results or [])
        self._chunks = list(chunks or [])

    async def complete(self, payload: dict[str, object], timeout: float) -> dict[str, object]:
        del timeout
        self.payloads.append(payload)
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, dict)
        return item

    async def stream(self, payload: dict[str, object], timeout: float):
        del timeout
        self.payloads.append(payload)
        for chunk in self._chunks:
            yield chunk


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        model_name="configured-model",
        parameters={"temperature": 0.2, "thinking": "disabled", "ignored": "no"},
        task_type="conversation",
    )


def _scope() -> ModelCallScope:
    return ModelCallScope(trace_id=uuid.uuid4())


def _adapter(client: _Client, config: object, logs: _Logs, retries: int = 1) -> ModelAdapter:
    return ModelAdapter(
        client=client,  # type: ignore[arg-type]
        settings=Settings(deepseek_api_key="test-key", deepseek_max_retries=retries, deepseek_timeout_seconds=1),
        configs=_Configs(config),  # type: ignore[arg-type]
        logs=logs,  # type: ignore[arg-type]
        session_factory=_Session,
    )


def _completion(content: str) -> dict[str, object]:
    return {
        "model": "configured-model",
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }


def test_payload_uses_the_configured_model_and_documented_fields() -> None:
    payload = build_chat_payload(
        "configured-model",
        [ChatMessage(role="user", content="你好")],
        {"temperature": 0.2, "thinking": "disabled", "api_style": "ignored"},
        json_object=True,
        stream=False,
    )
    assert payload["model"] == "configured-model"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert "api_style" not in payload
    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("app/modules/model_adapter").rglob("*.py"))
    assert "deepseek-flash" not in source
    assert "deepseek-v4-pro" not in source


def test_sse_done_marker_ends_the_stream() -> None:
    assert parse_sse_data_line("data: [DONE]") is not None
    event = parse_sse_data_line('data: {"choices":[{"delta":{"content":"你"}}]}')
    assert isinstance(event, dict)
    assert event["choices"][0]["delta"]["content"] == "你"


@pytest.mark.asyncio
async def test_http_client_posts_chat_completions_without_logging_the_key() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json=_completion("你好"))

    client = DeepSeekHttpClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    body = await client.complete({"model": "configured-model", "messages": []}, timeout=1)
    assert seen["path"] == "/chat/completions"
    assert seen["authorization"] == "Bearer test-key"
    assert body["choices"][0]["message"]["content"] == "你好"


@pytest.mark.asyncio
async def test_text_completion_retries_timeout_and_records_both_attempts() -> None:
    client = _Client([ModelTimeoutError("模型调用超时"), _completion("你好")])
    logs = _Logs()
    adapter = _adapter(client, _config(), logs)
    result = await adapter.complete_text(
        ModelConfigKey.CONVERSATION,
        [ChatMessage(role="user", content="你好")],
        _scope(),
    )
    assert result.content == "你好"
    assert result.input_tokens == 4
    assert client.payloads[0]["model"] == "configured-model"
    assert [item.status for item in logs.records] == [ModelCallStatus.TIMEOUT, ModelCallStatus.SUCCESS]
    assert all("你好" not in item.model_dump_json() for item in logs.records)


@pytest.mark.asyncio
async def test_structured_output_rejects_a_shape_the_model_did_not_match() -> None:
    client = _Client([_completion('{"primary_action":"quiet"}')])
    adapter = _adapter(client, _config(), _Logs(), retries=0)
    parsed = await adapter.complete_structured(
        ModelConfigKey.DECISION,
        [ChatMessage(role="system", content="只返回 JSON"), ChatMessage(role="user", content="决定")],
        _Probe,
        _scope(),
    )
    assert parsed.primary_action == "quiet"
    invalid = _adapter(_Client([_completion('{"other":1}')]), _config(), _Logs(), retries=0)
    with pytest.raises(ModelOutputError):
        await invalid.complete_structured(
            ModelConfigKey.DECISION,
            [ChatMessage(role="user", content="决定")],
            _Probe,
            _scope(),
        )


@pytest.mark.asyncio
async def test_embedding_is_refused_without_a_provider_call() -> None:
    client = _Client()
    adapter = _adapter(client, _config(), _Logs())
    with pytest.raises(ModelCapabilityError):
        await adapter.embed(ModelConfigKey.EMBEDDING, _scope())
    assert client.payloads == []


@pytest.mark.asyncio
async def test_missing_config_and_client_error_do_not_invent_text() -> None:
    client = _Client([ModelHttpError(400)])
    missing = _adapter(client, None, _Logs())
    with pytest.raises(Exception) as missing_error:
        await missing.complete_text(ModelConfigKey.MEMORY, [ChatMessage(role="user", content="记住")], _scope())
    assert missing_error.value.status_code == 404
    assert client.payloads == []
    failed = _adapter(_Client([ModelHttpError(400)]), _config(), _Logs(), retries=0)
    with pytest.raises(ModelHttpError):
        await failed.complete_text(ModelConfigKey.MEMORY, [ChatMessage(role="user", content="记住")], _scope())


@pytest.mark.asyncio
async def test_stream_yields_content_deltas_only() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "你"}}], "usage": None},
        {"choices": [{"delta": {"reasoning_content": "内部思考", "content": "好"}}], "usage": {"prompt_tokens": 2, "completion_tokens": 2}},
    ]
    client = _Client(chunks=chunks)
    logs = _Logs()
    adapter = _adapter(client, _config(), logs, retries=0)
    pieces = [
        piece
        async for piece in adapter.stream_text(
            ModelConfigKey.CONVERSATION,
            [ChatMessage(role="user", content="你好")],
            _scope(),
        )
    ]
    assert pieces == ["你", "好"]
    assert logs.records[0].status == ModelCallStatus.SUCCESS
    assert logs.records[0].output_tokens == 2
    assert "内部思考" not in logs.records[0].model_dump_json()


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


async def _remove_adapter_rows() -> None:
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                DELETE FROM model_call_logs
                WHERE trace_id = '22222222-2222-4222-8222-222222222222'
                   OR config_id IN (SELECT id FROM model_configs WHERE config_key = 'conversation_model')
                """
            )
        )
        await connection.execute(text("DELETE FROM model_configs WHERE config_key = 'conversation_model'"))


@pytest.mark.asyncio
async def test_adapter_writes_a_call_log_from_the_saved_config(database_ready: None) -> None:
    parked = await park_model_config("conversation_model")
    app = create_app()
    transport = ASGITransport(app=app)
    trace_id = "22222222-2222-4222-8222-222222222222"
    try:
        await _remove_adapter_rows()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/model-configs",
                json={"config_key": "conversation_model", "model_name": "configured-model", "parameters": {}},
            )
            assert created.status_code == 201
            adapter = ModelAdapter(
                client=_Client([_completion("收到")]),  # type: ignore[arg-type]
                settings=Settings(deepseek_api_key="test-key", deepseek_max_retries=0, deepseek_timeout_seconds=1),
                session_factory=get_session_factory(),
            )
            result = await adapter.complete_text(
                ModelConfigKey.CONVERSATION,
                [ChatMessage(role="user", content="在吗")],
                ModelCallScope(trace_id=uuid.UUID(trace_id)),
            )
            assert result.content == "收到"
            logs = await client.get("/api/model-call-logs", params={"trace_id": trace_id})
            assert logs.status_code == 200
            assert logs.json()[0]["model_name"] == "configured-model"
            assert logs.json()[0]["status"] == "success"
            assert "prompt" not in logs.json()[0]
    finally:
        await _remove_adapter_rows()
        await restore_model_config(*parked)
