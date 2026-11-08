"""无真实模型时的契约后端：用于联调、健康检查与 CI。"""

from __future__ import annotations

import asyncio
import struct
import wave
from io import BytesIO
from pathlib import Path

from audio_worker.schemas import AsrResult, TtsRequest, TtsResult


class StubAsrBackend:
    name = "stub"
    model_name = "stub-asr"
    loaded = False

    async def load(self) -> None:
        await asyncio.sleep(0)
        self.loaded = True

    async def recognize(self, audio_bytes: bytes, *, language: str = "auto") -> AsrResult:
        if not self.loaded:
            await self.load()
        duration_ms = _estimate_wav_duration_ms(audio_bytes)
        return AsrResult(
            text="（stub）语音识别结果",
            language="zh" if language in {"auto", "zh"} else language,
            emotion=None,
            audio_events=[],
            duration_ms=duration_ms,
            confidence=None,
            model_name=self.model_name,
            backend=self.name,
        )


class StubTtsBackend:
    name = "stub"
    model_name = "stub-tts"
    loaded = False

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    async def load(self) -> None:
        await asyncio.sleep(0)
        self.loaded = True

    async def synthesize(self, request: TtsRequest) -> TtsResult:
        if not self.loaded:
            await self.load()
        self._counter += 1
        path = self._output_dir / f"stub_{self._counter:06d}.wav"
        duration_ms = max(400, min(12000, len(request.text) * 80))
        await asyncio.to_thread(_write_silence_wav, path, request.sample_rate, duration_ms)
        return TtsResult(
            file_path=str(path.resolve()),
            format="wav",
            sample_rate=request.sample_rate,
            duration_ms=duration_ms,
            model_name=self.model_name,
            backend=self.name,
        )


def _estimate_wav_duration_ms(audio_bytes: bytes) -> int:
    if len(audio_bytes) < 44:
        return 0
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 16000
            return int(frames * 1000 / rate)
    except wave.Error:
        return max(0, (len(audio_bytes) - 44) // 32)


def _write_silence_wav(path: Path, sample_rate: int, duration_ms: int) -> None:
    frames = max(1, int(sample_rate * duration_ms / 1000))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))
