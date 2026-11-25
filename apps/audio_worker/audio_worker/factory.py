from __future__ import annotations

import logging

from audio_worker.backends.base import AsrBackend, TtsBackend
from audio_worker.backends.sensevoice import SenseVoiceAsrBackend, sensevoice_available
from audio_worker.backends.stub import StubAsrBackend, StubTtsBackend
from audio_worker.config import WorkerSettings

logger = logging.getLogger(__name__)


def build_asr_backend(settings: WorkerSettings) -> AsrBackend:
    mode = settings.asr_backend.strip().lower()
    if mode == "stub":
        return StubAsrBackend()
    if mode in {"sensevoice", "auto"} and sensevoice_available():
        return SenseVoiceAsrBackend(settings.asr_model_name, settings.model_dir / "asr")
    if mode == "sensevoice":
        logger.warning("SenseVoice requested but dependencies missing; using stub")
    return StubAsrBackend()


def build_tts_backend(settings: WorkerSettings) -> TtsBackend:
    """本地 CosyVoice 已移除。没有云端 provider 时只保留静音 stub。"""
    mode = settings.tts_backend.strip().lower()
    if mode not in {"", "stub"}:
        logger.warning("本地语音合成已移除（请求的后端是 %s），改用 stub", mode)
    return StubTtsBackend(settings.output_dir)
