from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from audio_worker.config import get_settings
from audio_worker.factory import build_asr_backend, build_tts_backend
from audio_worker.gpu import read_gpu_status
from audio_worker.queue import InferenceQueue
from audio_worker.schemas import AsrResult, HealthResponse, TtsRequest, TtsResult

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    asr = build_asr_backend(settings)
    tts = build_tts_backend(settings)
    queue = InferenceQueue(maxsize=settings.max_queue_size)
    app.state.asr = asr
    app.state.tts = tts
    app.state.queue = queue
    app.state.settings = settings
    try:
        await asr.load()
    except Exception:
        logger.exception("ASR load failed; worker stays up in degraded mode")
    try:
        await tts.load()
    except Exception:
        logger.exception("TTS load failed; worker stays up in degraded mode")
    yield


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    app = FastAPI(title="AI Companion Audio Worker", version="0.1.0", lifespan=lifespan)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        gpu = read_gpu_status()
        asr = app.state.asr
        tts = app.state.tts
        queue: InferenceQueue = app.state.queue
        ready = asr.loaded and tts.loaded
        return HealthResponse(
            status="ok" if ready else "degraded",
            asr_backend=asr.name,
            tts_backend=tts.name,
            asr_loaded=bool(asr.loaded),
            tts_loaded=bool(tts.loaded),
            gpu_available=gpu.available,
            gpu_name=gpu.name,
            gpu_memory_used_mb=gpu.memory_used_mb,
            gpu_memory_total_mb=gpu.memory_total_mb,
            queue_depth=queue.depth,
        )

    @app.post("/v1/asr", response_model=AsrResult)
    async def asr_recognize(
        audio: UploadFile = File(...),
        language: str = Form(default="auto"),
    ) -> AsrResult:
        payload = await audio.read()
        if not payload:
            raise HTTPException(status_code=400, detail="空音频")
        try:
            return await app.state.asr.recognize(payload, language=language)
        except Exception as exc:
            logger.exception("ASR failed")
            raise HTTPException(status_code=503, detail=f"ASR 失败: {exc}") from exc

    @app.post("/v1/tts", response_model=TtsResult)
    async def tts_synthesize(body: TtsRequest) -> TtsResult:
        queue: InferenceQueue = app.state.queue

        async def _work() -> TtsResult:
            return await app.state.tts.synthesize(body)

        try:
            return await queue.run(_work)
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("TTS failed")
            raise HTTPException(status_code=503, detail=f"TTS 失败: {exc}") from exc

    @app.post("/v1/tts/stream")
    async def tts_synthesize_stream(body: TtsRequest):
        """契约流：先完整合成，再按小 WAV 分块以 NDJSON 返回。真实 CosyVoice 流式可替换此实现。"""
        from fastapi.responses import StreamingResponse

        from audio_worker.stream_chunks import iter_wav_ndjson

        queue: InferenceQueue = app.state.queue

        async def _work() -> TtsResult:
            return await app.state.tts.synthesize(body)

        try:
            result = await queue.run(_work)
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("TTS failed")
            raise HTTPException(status_code=503, detail=f"TTS 失败: {exc}") from exc

        async def frames():
            async for line in iter_wav_ndjson(result.file_path, sample_rate=result.sample_rate):
                yield line

        return StreamingResponse(frames(), media_type="application/x-ndjson")

    return app


app = create_app()
