import pytest
from pytest import MonkeyPatch

from app.modules.audio.adapters.worker_client import AudioWorkerClient
from app.modules.audio.domain.expression import VoiceExpressionProfile
from app.modules.audio.services.audio_expression_service import AudioExpressionService


@pytest.mark.asyncio
async def test_worker_health_unreachable() -> None:
    client = AudioWorkerClient("http://127.0.0.1:1", timeout_seconds=0.2)
    health = await client.health()
    assert health.reachable is False
    assert health.status == "down"


def test_expression_service_wrapper() -> None:
    service = AudioExpressionService()
    result = service.build(
        primary="sadness",
        levels={"sadness": 48},
        voice_expression=VoiceExpressionProfile(emotional_expressiveness=0.5),
    )
    assert result.primary_emotion == "sadness"
    assert 0 < result.intensity <= 0.5


@pytest.mark.asyncio
async def test_worker_recognize_uses_multipart(monkeypatch: MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "text": "今天有点累",
                "language": "zh",
                "emotion": "sad",
                "audio_events": [],
                "duration_ms": 1200,
                "confidence": None,
                "model_name": "stub-asr",
                "backend": "stub",
            }

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            calls["kwargs"] = kwargs

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, path: str, files: object = None, data: object = None, json: object = None) -> _Resp:
            calls["path"] = path
            calls["files"] = files
            calls["data"] = data
            return _Resp()

    monkeypatch.setattr("app.modules.audio.adapters.worker_client.httpx.AsyncClient", _Client)
    client = AudioWorkerClient("http://example.test")
    result = await client.recognize(b"abc", language="zh")
    assert result.text == "今天有点累"
    assert calls["path"] == "/v1/asr"
    assert calls["data"] == {"language": "zh"}
