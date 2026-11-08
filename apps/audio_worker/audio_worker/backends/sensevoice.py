"""SenseVoice 后端。依赖 funasr；不可用时由工厂回退 stub。"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import wave
from io import BytesIO
from pathlib import Path

from audio_worker.schemas import AsrResult

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<\|[^|]+\|>")


class SenseVoiceAsrBackend:
    name = "sensevoice"
    loaded = False

    def __init__(self, model_name: str, model_dir: Path) -> None:
        self.model_name = model_name
        self._model_dir = model_dir
        self._model: object | None = None

    async def load(self) -> None:
        if self.loaded:
            return
        await asyncio.to_thread(self._load_sync)
        self.loaded = True

    def _load_sync(self) -> None:
        from funasr import AutoModel

        self._model_dir.mkdir(parents=True, exist_ok=True)
        # FunASR / ModelScope 常用 id：iic/SenseVoiceSmall
        model_id = self.model_name
        if model_id in {"FunAudioLLM/SenseVoiceSmall", "SenseVoiceSmall"}:
            model_id = "iic/SenseVoiceSmall"
        cache_dir = str(self._model_dir)
        os_environ_set = _maybe_set_modelscope_cache(cache_dir)
        try:
            self._model = AutoModel(
                model=model_id,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device="cpu",
                disable_update=True,
            )
        finally:
            if os_environ_set:
                os_environ_set()
        logger.info("SenseVoice loaded: %s", model_id)

    async def recognize(self, audio_bytes: bytes, *, language: str = "auto") -> AsrResult:
        if not self.loaded:
            await self.load()
        return await asyncio.to_thread(self._recognize_sync, audio_bytes, language)

    def _recognize_sync(self, audio_bytes: bytes, language: str) -> AsrResult:
        assert self._model is not None
        duration_ms = _estimate_wav_duration_ms(audio_bytes)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            path = tmp.name
        try:
            kwargs: dict[str, object] = {
                "input": path,
                "use_itn": True,
                "batch_size_s": 60,
            }
            if language and language != "auto":
                kwargs["language"] = language
            raw = self._model.generate(**kwargs)  # type: ignore[operator]
            text, emotion, events = _parse_sensevoice(raw)
            return AsrResult(
                text=text,
                language=None if language == "auto" else language,
                emotion=emotion,
                audio_events=events,
                duration_ms=duration_ms,
                confidence=None,
                model_name=self.model_name,
                backend=self.name,
            )
        finally:
            Path(path).unlink(missing_ok=True)


def sensevoice_available() -> bool:
    try:
        import funasr  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def _maybe_set_modelscope_cache(cache_dir: str):
    import os

    key = "MODELSCOPE_CACHE"
    previous = os.environ.get(key)
    os.environ[key] = cache_dir

    def restore() -> None:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous

    return restore


def _parse_sensevoice(raw: object) -> tuple[str, str | None, list[str]]:
    if not isinstance(raw, list) or not raw:
        return "", None, []
    first = raw[0]
    if not isinstance(first, dict):
        return _clean_text(str(first)), None, []

    raw_text = str(first.get("text") or first.get("preds") or "")
    emotion = first.get("emotion")
    events_raw = first.get("event") or first.get("audio_events") or []
    events = [str(item) for item in events_raw] if isinstance(events_raw, list) else []

    # SenseVoice 常把标签嵌在文本里：<|zh|><|NEUTRAL|><|Speech|>正文
    tags = _TAG_RE.findall(raw_text)
    text = _clean_text(raw_text)
    if emotion is None:
        for tag in tags:
            inner = tag.strip("<|>")
            if inner.upper() in {
                "HAPPY",
                "SAD",
                "ANGRY",
                "NEUTRAL",
                "FEARFUL",
                "DISGUSTED",
                "SURPRISED",
            }:
                emotion = inner.lower()
                break
    if not events:
        for tag in tags:
            inner = tag.strip("<|>")
            if inner in {"Speech", "BGM", "Applause", "Laughter", "Cry", "Sneeze", "Breath", "Cough"}:
                events.append(inner)

    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        text = rich_transcription_postprocess(raw_text).strip() or text
    except Exception:
        pass

    return text, str(emotion) if emotion else None, events


def _clean_text(raw: str) -> str:
    return _TAG_RE.sub("", raw).strip()


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
