import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audio.domain.schemas import (
    AsrRecognizeResponse,
    AudioHealthResponse,
    AudioTaskResponse,
    TtsSynthesizeResponse,
    VoiceProfileResponse,
)
from app.modules.audio.domain.stream_schemas import encode_audio_sse
from app.modules.audio.services.audio_manager import AudioManager
from app.modules.audio.services.voice_profile_service import VoiceProfileService, to_voice_response
from app.shared.database.session import get_session

router = APIRouter(prefix="/audio", tags=["audio"])
audio_manager = AudioManager()
voice_service = VoiceProfileService()


class TtsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: uuid.UUID
    voice_profile_id: uuid.UUID | None = None


@router.get("/health", response_model=AudioHealthResponse)
async def audio_health() -> AudioHealthResponse:
    return await audio_manager.health()


@router.post(
    "/users/{user_id}/companions/{companion_id}/asr",
    response_model=AsrRecognizeResponse,
)
async def recognize_speech(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    audio: UploadFile = File(...),
    language: str = Form(default="auto"),
    conversation_id: uuid.UUID | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> AsrRecognizeResponse:
    payload = await audio.read()
    filename = audio.filename or "audio.wav"
    return await audio_manager.recognize(
        session,
        user_id,
        companion_id,
        payload,
        language=language,
        conversation_id=conversation_id,
        filename=filename,
    )


@router.post(
    "/users/{user_id}/companions/{companion_id}/tts",
    response_model=TtsSynthesizeResponse,
)
async def synthesize_speech(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: TtsBody,
    session: AsyncSession = Depends(get_session),
) -> TtsSynthesizeResponse:
    return await audio_manager.synthesize_for_message(
        session,
        user_id,
        companion_id,
        body.message_id,
        voice_profile_id=body.voice_profile_id,
    )


@router.post(
    "/users/{user_id}/companions/{companion_id}/tts/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def synthesize_speech_stream(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    body: TtsBody,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    stream = audio_manager.iter_stream_for_message(
        session,
        user_id,
        companion_id,
        body.message_id,
        voice_profile_id=body.voice_profile_id,
    )

    async def frames() -> AsyncIterator[str]:
        async for event in stream:
            yield encode_audio_sse(event)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/users/{user_id}/companions/{companion_id}/voices",
    response_model=list[VoiceProfileResponse],
)
async def list_voices(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[VoiceProfileResponse]:
    await voice_service.ensure_default(session, user_id, companion_id)
    profiles = await voice_service.list_voices(session, user_id, companion_id)
    return [to_voice_response(item) for item in profiles]


@router.post(
    "/users/{user_id}/companions/{companion_id}/tasks/{task_id}/cancel",
    response_model=AudioTaskResponse,
)
async def cancel_audio_task(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AudioTaskResponse:
    return await audio_manager.cancel_task(session, user_id, companion_id, task_id)


@router.get("/users/{user_id}/companions/{companion_id}/assets/{asset_id}")
async def download_audio_asset(
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    path: Path = await audio_manager.resolve_asset_file(session, user_id, companion_id, asset_id)
    return FileResponse(path, media_type="audio/wav", filename=path.name)
