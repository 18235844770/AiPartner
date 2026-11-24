"""Audio Worker HTTP 客户端。业务模块不直接碰推理 SDK。"""

from __future__ import annotations

import logging

import httpx

from app.modules.audio.domain.schemas import WorkerAsrResult, WorkerHealth, WorkerTtsResult
from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelHttpError, ModelTimeoutError

logger = logging.getLogger(__name__)


class AudioWorkerClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def health(self) -> WorkerHealth:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
                response = await client.get("/health")
            response.raise_for_status()
            data = response.json()
            return WorkerHealth(reachable=True, **data)
        except Exception as exc:
            logger.warning("audio worker unreachable: %s", exc)
            return WorkerHealth(
                status="down",
                asr_backend="unknown",
                tts_backend="unknown",
                asr_loaded=False,
                tts_loaded=False,
                gpu_available=False,
                reachable=False,
                error=str(exc) or type(exc).__name__,
            )

    async def recognize(self, audio_bytes: bytes, *, filename: str = "audio.wav", language: str = "auto") -> WorkerAsrResult:
        files = {"audio": (filename, audio_bytes, "audio/wav")}
        data = {"language": language}
        body = await self._post_multipart("/v1/asr", files=files, data=data)
        return WorkerAsrResult.model_validate(body)

    async def synthesize(
        self,
        *,
        text: str,
        speed: float = 1.0,
        volume: float = 1.0,
        instruction: str | None = None,
        reference_audio_path: str | None = None,
        reference_text: str | None = None,
        sample_rate: int = 24000,
        provider: str | None = None,
        provider_model: str | None = None,
        provider_voice_id: str | None = None,
    ) -> WorkerTtsResult:
        payload = {
            "text": text,
            "speed": speed,
            "volume": volume,
            "instruction": instruction,
            "reference_audio_path": reference_audio_path,
            "reference_text": reference_text,
            "sample_rate": sample_rate,
            "provider": provider,
            "provider_model": provider_model,
            "provider_voice_id": provider_voice_id,
        }
        body = await self._post_json("/v1/tts", payload)
        return WorkerTtsResult.model_validate(body)

    async def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("音频推理超时") from exc
        except httpx.HTTPError as exc:
            raise ModelAdapterError("音频 Worker 不可用") from exc
        return self._read(response)

    async def _post_multipart(
        self,
        path: str,
        *,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
    ) -> dict[str, object]:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.post(path, files=files, data=data)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("音频推理超时") from exc
        except httpx.HTTPError as exc:
            raise ModelAdapterError("音频 Worker 不可用") from exc
        return self._read(response)

    def _read(self, response: httpx.Response) -> dict[str, object]:
        if response.status_code >= 400:
            raise ModelHttpError(response.status_code)
        body = response.json()
        if not isinstance(body, dict):
            raise ModelAdapterError("音频 Worker 响应无效")
        return body
