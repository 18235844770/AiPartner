"""Fish、豆包语音合成 3.0、龙安欢的云端合成。密钥只从 Worker 配置读取。"""

from __future__ import annotations

import base64
import json
import struct
import uuid
import wave
from io import BytesIO

import httpx

from audio_worker.config import WorkerSettings
from audio_worker.schemas import TtsRequest, TtsResult

_FISH_FREE = "s2.1-pro-free"


class CloudTtsError(Exception):
    pass


def fish_text(text: str, instruction: str | None) -> str:
    cleaned = (instruction or "").strip()
    if not cleaned:
        return text
    return f"[{cleaned}]\n{text}"


def repair_wav(payload: bytes, sample_rate: int) -> bytes:
    if len(payload) < 44 or payload[:4] != b"RIFF":
        raise CloudTtsError("云端响应不是 WAV")
    pcm = payload[44:]
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm


def wav_duration_ms(payload: bytes) -> int:
    with wave.open(BytesIO(payload), "rb") as handle:
        rate = handle.getframerate() or 1
        return int(handle.getnframes() / rate * 1000)


async def synthesize_cloud(settings: WorkerSettings, request: TtsRequest) -> TtsResult:
    provider = (request.provider or "").strip()
    voice_id = (request.provider_voice_id or "").strip()
    model = (request.provider_model or "").strip()
    if provider not in {"fish", "volcengine", "dashscope"} or not voice_id or not model:
        raise CloudTtsError("云端音色参数不完整")
    async with httpx.AsyncClient(timeout=90.0) as client:
        if provider == "fish":
            audio, model = await _fish(client, settings, request, voice_id, model)
            sample_rate = 24000
        elif provider == "volcengine":
            audio = await _volcengine(client, settings, request, voice_id, model)
            sample_rate = 24000
        else:
            audio = await _dashscope(client, settings, request, voice_id, model)
            sample_rate = 24000
    audio = repair_wav(audio, sample_rate)
    path = settings.output_dir / f"{uuid.uuid4().hex}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return TtsResult(
        file_path=str(path),
        format="wav",
        sample_rate=sample_rate,
        duration_ms=wav_duration_ms(audio),
        model_name=f"{provider}:{voice_id}:{model}",
        backend=provider,
    )


async def _fish(
    client: httpx.AsyncClient,
    settings: WorkerSettings,
    request: TtsRequest,
    voice_id: str,
    model: str,
) -> tuple[bytes, str]:
    key = settings.fish_api_key.strip()
    if not key:
        raise CloudTtsError("缺少 FISH_API_KEY")
    tried = model
    response = await _fish_request(client, key, voice_id, request, model)
    if response.status_code == 402 and model != _FISH_FREE:
        tried = _FISH_FREE
        response = await _fish_request(client, key, voice_id, request, tried)
    _raise_for_status(response)
    if response.content[:1] in (b"{", b"["):
        raise CloudTtsError(response.text[:400])
    return response.content, tried


async def _fish_request(
    client: httpx.AsyncClient,
    key: str,
    voice_id: str,
    request: TtsRequest,
    model: str,
) -> httpx.Response:
    return await client.post(
        "https://api.fish.audio/v1/tts",
        headers={"Authorization": f"Bearer {key}", "model": model},
        json={
            "text": fish_text(request.text, request.instruction),
            "reference_id": voice_id,
            "format": "wav",
            "sample_rate": 24000,
            "language": "zh",
        },
    )


async def _volcengine(
    client: httpx.AsyncClient,
    settings: WorkerSettings,
    request: TtsRequest,
    voice_id: str,
    model: str,
) -> bytes:
    key = settings.volcengine_api_key.strip()
    if not key:
        raise CloudTtsError("缺少 VOLCENGINE_API_KEY")
    instruction = (request.instruction or "").strip() or "语气自然、放松，像日常聊天"
    speed = min(2.0, max(0.5, request.speed))
    response = await client.post(
        f"https://voice.cn-beijing.volces.com/api/v3/text-to-speech/{voice_id}/streaming",
        headers={"X-Api-Key": key, "X-Request-Id": str(uuid.uuid4())},
        json={
            "text": request.text,
            "model_id": model,
            "language_code": "zh",
            "output_format": {"format": "pcm", "sample_rate": 24000},
            "voice_settings": {"speed": speed, "instructions": [instruction]},
        },
    )
    _raise_for_status(response)
    audio = bytearray()
    error = ""
    for line in response.text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        event = json.loads(stripped)
        if event.get("event") == "audio" and event.get("audio"):
            audio.extend(base64.b64decode(event["audio"]))
        elif event.get("event") == "error":
            error = json.dumps(event, ensure_ascii=False)[:400]
    if error and not audio:
        raise CloudTtsError(error)
    if not audio:
        raise CloudTtsError(response.text[:400])
    return _pcm_to_wav(bytes(audio), 24000)


async def _dashscope(
    client: httpx.AsyncClient,
    settings: WorkerSettings,
    request: TtsRequest,
    voice_id: str,
    model: str,
) -> bytes:
    key = settings.dashscope_api_key.strip()
    workspace = settings.dashscope_workspace_id.strip()
    if not key or not workspace:
        raise CloudTtsError("缺少 DASHSCOPE_API_KEY 或 DASHSCOPE_WORKSPACE_ID")
    response = await client.post(
        f"https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "input": {
                "text": request.text,
                "voice": voice_id,
                "format": "wav",
                "sample_rate": 24000,
                "volume": 50,
                "pitch": 1.0,
                "seed": 0,
                "language_hints": ["zh"],
                "instruction": request.instruction or "你正在进行闲聊对话，你说话的情感是neutral。",
            },
        },
    )
    _raise_for_status(response)
    body = response.json()
    audio_url = ((body.get("output") or {}).get("audio") or {}).get("url")
    if not isinstance(audio_url, str) or not audio_url:
        raise CloudTtsError("语音合成没有返回音频地址")
    downloaded = await client.get(audio_url)
    _raise_for_status(downloaded)
    return downloaded.content


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise CloudTtsError(f"HTTP {response.status_code}: {response.text[:400]}")
