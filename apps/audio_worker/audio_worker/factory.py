from __future__ import annotations

import logging

from audio_worker.backends.base import AsrBackend, TtsBackend
from audio_worker.backends.cosyvoice import CosyVoiceTtsBackend, cosyvoice_available
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
    mode = settings.tts_backend.strip().lower()
    if mode == "stub":
        return StubTtsBackend(settings.output_dir)
    repo = settings.cosyvoice_repo
    if mode in {"cosyvoice3", "cosyvoice", "auto"} and cosyvoice_available(repo):
        return CosyVoiceTtsBackend(
            settings.tts_model_name,
            settings.model_dir / "tts",
            settings.output_dir,
            repo_dir=repo,
            default_prompt_wav=settings.tts_default_prompt_wav,
            fp16=settings.tts_fp16,
        )
    if mode in {"cosyvoice3", "cosyvoice"}:
        logger.warning("CosyVoice requested but repo/deps missing; using stub")
    return StubTtsBackend(settings.output_dir)
