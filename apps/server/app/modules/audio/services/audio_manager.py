"""Audio 编排：健康检查、ASR、固定音色 TTS、资产与取消。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.modules.audio.adapters.worker_client import AudioWorkerClient
from app.modules.audio.domain.enums import AudioTaskStatus, AudioTaskType
from app.modules.audio.domain.expression import TTS_CONTRACT_VERSION, prepare_speak_text
from app.modules.audio.domain.preset_voices import cache_matches, render_preset_instruction
from app.modules.audio.domain.schemas import (
    AsrRecognizeResponse,
    AudioHealthResponse,
    AudioTaskResponse,
    TtsSynthesizeResponse,
)
from app.modules.audio.domain.stream_schemas import (
    AudioCancelled,
    AudioChunk,
    AudioCompleted,
    AudioFailed,
    AudioStarted,
    AudioStreamEvent,
    b64_bytes,
)
from app.modules.audio.domain.wav_chunks import split_wav_file
from app.modules.audio.repositories.audio_repository import (
    AudioAssetRepository,
    AudioTaskRepository,
    VoiceProfileRepository,
)
from app.modules.audio.repositories.models import AudioAsset, AudioTask
from app.modules.audio.services.audio_expression_service import AudioExpressionService
from app.modules.audio.services.preset_voice_service import PresetVoiceService
from app.modules.audio.services.voice_profile_service import VoiceProfileService
from app.modules.conversation.services.conversation_service import ConversationService
from app.modules.identity.services.identity_service import IdentityService
from app.modules.infrastructure.api.schemas import RecordModelCallRequest
from app.modules.infrastructure.domain.enums import ModelCallStatus, ModelProvider, ModelTaskType
from app.modules.infrastructure.services.model_call_log_service import ModelCallLogService
from app.modules.infrastructure.services.model_config_service import ModelConfigService
from app.modules.model_adapter.domain.errors import ModelAdapterError
from app.modules.persona.domain.voice_expression import resolve_voice_expression
from app.modules.persona.services.persona_service import PersonaService
from app.modules.state.domain.snapshots import EmotionState
from app.modules.state.services.state_service import StateService
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import AppError, NotFoundError

logger = logging.getLogger(__name__)


class AudioManager:
    def __init__(
        self,
        worker: AudioWorkerClient | None = None,
        identity: IdentityService | None = None,
        tasks: AudioTaskRepository | None = None,
        assets: AudioAssetRepository | None = None,
        voices: VoiceProfileRepository | None = None,
        voice_service: VoiceProfileService | None = None,
        presets: PresetVoiceService | None = None,
        conversations: ConversationService | None = None,
        personas: PersonaService | None = None,
        states: StateService | None = None,
        expression: AudioExpressionService | None = None,
        configs: ModelConfigService | None = None,
        logs: ModelCallLogService | None = None,
        settings: Settings | None = None,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._worker = worker or AudioWorkerClient(
            self._settings.audio_worker_url,
            timeout_seconds=self._settings.audio_worker_timeout_seconds,
        )
        self._identity = identity or IdentityService()
        self._tasks = tasks or AudioTaskRepository()
        self._assets = assets or AudioAssetRepository()
        self._voices = voices or VoiceProfileRepository()
        self._voice_service = voice_service or VoiceProfileService(
            voices=self._voices,
            identity=self._identity,
            settings=self._settings,
        )
        self._presets = presets or PresetVoiceService(identity=self._identity)
        self._conversations = conversations or ConversationService()
        self._personas = personas or PersonaService()
        self._states = states or StateService()
        self._expression = expression or AudioExpressionService()
        self._configs = configs or ModelConfigService()
        self._logs = logs or ModelCallLogService()
        self._session_factory = session_factory or get_session_factory()

    async def health(self) -> AudioHealthResponse:
        worker = await self._worker.health()
        status = "ok" if worker.reachable and worker.status == "ok" else "degraded"
        return AudioHealthResponse(status=status, worker=worker)

    async def ensure_local_audio_configs(self) -> None:
        await self._configs.ensure_local_audio(
            asr_model_name=self._settings.asr_model_name,
            tts_model_name=self._settings.tts_model_name,
        )

    async def recognize(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        audio_bytes: bytes,
        *,
        language: str = "auto",
        conversation_id: uuid.UUID | None = None,
        filename: str = "audio.wav",
        trace_id: uuid.UUID | None = None,
    ) -> AsrRecognizeResponse:
        await self.ensure_local_audio_configs()
        now = datetime.now(UTC)
        task = AudioTask(
            companion_id=companion_id,
            conversation_id=conversation_id,
            task_type=AudioTaskType.ASR.value,
            task_status=AudioTaskStatus.RUNNING.value,
            created_at=now,
            completed_at=None,
        )
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            await self._tasks.add(session, task)

        started = time.perf_counter()
        started_at = datetime.now(UTC)
        trace = trace_id or uuid.uuid4()
        try:
            result = await self._worker.recognize(audio_bytes, filename=filename, language=language)
        except ModelAdapterError as exc:
            await self._fail_task(session, task.id, companion_id, exc)
            await self._log_call(
                ModelTaskType.ASR,
                trace,
                user_id,
                companion_id,
                conversation_id,
                started_at,
                ok=False,
                latency_ms=_latency(started),
                model_name=self._settings.asr_model_name,
                error=str(exc) or exc.__class__.__name__,
            )
            raise

        completed = datetime.now(UTC)
        async with session.begin():
            locked = await self._tasks.get(session, task.id, companion_id)
            if locked is None:
                raise ModelAdapterError("ASR 任务丢失")
            locked.task_status = AudioTaskStatus.COMPLETED.value
            locked.completed_at = completed
            locked.duration_ms = result.duration_ms
            locked.model_name = result.model_name
            locked.source_text = result.text
            await session.flush()

        await self._log_call(
            ModelTaskType.ASR,
            trace,
            user_id,
            companion_id,
            conversation_id,
            started_at,
            ok=True,
            latency_ms=_latency(started),
            model_name=result.model_name,
        )
        return AsrRecognizeResponse(
            task_id=task.id,
            text=result.text,
            language=result.language,
            emotion=result.emotion,
            status=AudioTaskStatus.COMPLETED,
            duration_ms=result.duration_ms,
        )

    async def synthesize_for_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
        *,
        voice_profile_id: uuid.UUID | None = None,
        trace_id: uuid.UUID | None = None,
    ) -> TtsSynthesizeResponse:
        await self.ensure_local_audio_configs()
        profile = await self._voice_service.ensure_default(session, user_id, companion_id)
        if voice_profile_id is not None:
            async with session.begin():
                await self._identity.get_owned_companion(session, user_id, companion_id)
                chosen = await self._voices.get(session, voice_profile_id, companion_id)
                if chosen is None or not chosen.enabled:
                    raise NotFoundError("音色不存在")
                profile = chosen
        preset = await self._presets.selected_preset(session, user_id, companion_id)
        preset_key = preset.cache_key if preset is not None else None

        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            existing = await self._tasks.get_completed_tts_for_message(session, companion_id, message_id)
            if existing is not None and _tts_cache_reusable(existing.expression_json) and cache_matches(
                existing.model_name, preset_key
            ):
                asset = await self._assets.get_by_task(session, existing.id, companion_id)
                if asset is not None:
                    return TtsSynthesizeResponse(
                        task_id=existing.id,
                        status=AudioTaskStatus.COMPLETED,
                        message_id=message_id,
                        audio_url=_asset_url(user_id, companion_id, asset.id),
                        format=asset.format,
                        sample_rate=asset.sample_rate,
                    )

        message = await self._conversations.get_owned_message(session, user_id, companion_id, message_id)
        if message.sender_type != "companion":
            raise AppError("只能为陪伴者消息合成语音")
        text = prepare_speak_text(message.content)
        if not text:
            raise AppError("消息内容为空或无可朗读正文")

        expression = await self._build_expression(session, user_id, companion_id)
        now = datetime.now(UTC)
        task = AudioTask(
            companion_id=companion_id,
            conversation_id=message.conversation_id,
            message_id=message_id,
            voice_profile_id=profile.id,
            task_type=AudioTaskType.TTS.value,
            task_status=AudioTaskStatus.RUNNING.value,
            source_text=text,
            speak_text=text,
            expression_json=expression.model_dump(),
            created_at=now,
            completed_at=None,
        )
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            await self._tasks.add(session, task)

        started = time.perf_counter()
        started_at = datetime.now(UTC)
        trace = trace_id or uuid.uuid4()
        try:
            ref_text = (profile.reference_text or "").strip()
            ref_path = profile.reference_audio_path
            # 占位参考文案/静音 stub 不得下发给 Worker，否则会被念进语音
            if "默认参考音频" in ref_text or ref_text in {
                "这是默认参考音频对应的文字。",
                "这是默认参考音频对应的文字",
            }:
                ref_text = None
                ref_path = None
            elif ref_path and "reference_stub" in Path(ref_path).name.lower():
                ref_path = None
                ref_text = None
            instruction = expression.tts_instruction
            if preset is not None:
                instruction = render_preset_instruction(preset, expression.primary_emotion, instruction)
            result = await self._worker.synthesize(
                text=text,
                speed=round(profile.default_speed * expression.speed, 3),
                volume=expression.volume,
                instruction=instruction,
                reference_audio_path=None if preset is not None else ref_path,
                reference_text=None if preset is not None else ref_text,
                provider=None if preset is None else preset.provider,
                provider_model=None if preset is None else preset.model,
                provider_voice_id=None if preset is None else preset.voice_id,
            )
        except ModelAdapterError as exc:
            await self._fail_task(session, task.id, companion_id, exc)
            await self._log_call(
                ModelTaskType.TTS,
                trace,
                user_id,
                companion_id,
                message.conversation_id,
                started_at,
                ok=False,
                latency_ms=_latency(started),
                model_name=self._settings.tts_model_name,
                error=str(exc) or exc.__class__.__name__,
            )
            raise

        stored = self._store_asset_file(companion_id, task.id, Path(result.file_path))
        checksum = _sha256_file(stored)
        completed = datetime.now(UTC)
        asset_id = uuid.uuid4()
        async with session.begin():
            locked = await self._tasks.get(session, task.id, companion_id)
            if locked is None:
                raise ModelAdapterError("TTS 任务丢失")
            if locked.task_status == AudioTaskStatus.CANCELLED.value:
                raise ModelAdapterError("TTS 已取消")
            locked.task_status = AudioTaskStatus.COMPLETED.value
            locked.completed_at = completed
            locked.duration_ms = result.duration_ms
            locked.model_name = result.model_name
            asset = AudioAsset(
                id=asset_id,
                companion_id=companion_id,
                audio_task_id=task.id,
                message_id=message_id,
                file_path=str(stored),
                format=result.format,
                sample_rate=result.sample_rate,
                duration_ms=result.duration_ms,
                file_size=stored.stat().st_size,
                checksum=checksum,
                created_at=completed,
            )
            await self._assets.add(session, asset)

        await self._log_call(
            ModelTaskType.TTS,
            trace,
            user_id,
            companion_id,
            message.conversation_id,
            started_at,
            ok=True,
            latency_ms=_latency(started),
            model_name=result.model_name,
        )
        return TtsSynthesizeResponse(
            task_id=task.id,
            status=AudioTaskStatus.COMPLETED,
            message_id=message_id,
            audio_url=_asset_url(user_id, companion_id, asset_id),
            format=result.format,
            sample_rate=result.sample_rate,
            expression=expression,
        )

    async def iter_stream_for_message(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
        *,
        voice_profile_id: uuid.UUID | None = None,
        chunk_ms: int = 400,
    ) -> AsyncIterator[AudioStreamEvent]:
        """先完成合成（或复用资产），再以 SSE 分块下发，便于客户端边收边播。"""
        sequence = 0
        task_id: uuid.UUID | None = None
        try:
            result = await self.synthesize_for_message(
                session,
                user_id,
                companion_id,
                message_id,
                voice_profile_id=voice_profile_id,
            )
            task_id = result.task_id
            path = await self._asset_path_for_task(session, user_id, companion_id, result.task_id)
            sample_rate, chunks = await asyncio.to_thread(split_wav_file, path, chunk_ms=chunk_ms)
            yield AudioStarted(
                task_id=result.task_id,
                message_id=message_id,
                format=result.format or "wav",
                sample_rate=sample_rate,
                sequence=sequence,
            )
            sequence += 1
            for index, chunk in enumerate(chunks):
                if await self._is_cancelled(result.task_id, companion_id):
                    yield AudioCancelled(
                        task_id=result.task_id,
                        message_id=message_id,
                        sequence=sequence,
                    )
                    return
                yield AudioChunk(
                    task_id=result.task_id,
                    message_id=message_id,
                    chunk_index=index,
                    sample_rate=sample_rate,
                    format="wav",
                    data_base64=b64_bytes(chunk),
                    is_last=index == len(chunks) - 1,
                    sequence=sequence,
                )
                sequence += 1
                await asyncio.sleep(0)
            yield AudioCompleted(
                task_id=result.task_id,
                message_id=message_id,
                audio_url=result.audio_url,
                format=result.format or "wav",
                sample_rate=sample_rate,
                duration_ms=0,
                sequence=sequence,
            )
        except asyncio.CancelledError:
            if task_id is not None:
                yield AudioCancelled(task_id=task_id, message_id=message_id, sequence=sequence)
            raise
        except Exception as exc:
            logger.exception("tts stream failed")
            if task_id is None:
                task_id = uuid.uuid4()
            yield AudioFailed(
                task_id=task_id,
                message_id=message_id,
                code=getattr(exc, "code", "tts_stream_failed"),
                message=str(exc) or exc.__class__.__name__,
                sequence=sequence,
            )

    async def _asset_path_for_task(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> Path:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            asset = await self._assets.get_by_task(session, task_id, companion_id)
            if asset is None:
                raise NotFoundError("音频资产不存在")
            path = Path(asset.file_path)
            if not path.is_file():
                raise NotFoundError("音频文件不存在")
            return path

    async def _is_cancelled(self, task_id: uuid.UUID, companion_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                task = await self._tasks.get(session, task_id, companion_id)
                return task is not None and task.task_status == AudioTaskStatus.CANCELLED.value

    async def cancel_task(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> AudioTaskResponse:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            task = await self._tasks.get(session, task_id, companion_id)
            if task is None:
                raise NotFoundError("音频任务不存在")
            if task.task_status in {
                AudioTaskStatus.COMPLETED.value,
                AudioTaskStatus.FAILED.value,
                AudioTaskStatus.CANCELLED.value,
            }:
                return _task_response(task)
            task.task_status = AudioTaskStatus.CANCELLED.value
            task.completed_at = datetime.now(UTC)
            await session.flush()
            return _task_response(task)

    async def resolve_asset_file(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> Path:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            asset = await self._assets.get(session, asset_id, companion_id)
            if asset is None:
                raise NotFoundError("音频资产不存在")
            path = Path(asset.file_path)
            if not path.is_file():
                raise NotFoundError("音频文件不存在")
            return path

    async def _build_expression(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ):
        voice_profile = resolve_voice_expression(None)
        try:
            _profile, version = await self._personas.get_current(session, user_id, companion_id)
            voice_profile = resolve_voice_expression(version.behavior_traits, mbti_type=version.mbti_type)
        except NotFoundError:
            logger.info("persona missing for companion %s; using default voice expression", companion_id)

        primary = "calm"
        secondary: list[str] = []
        levels: dict[str, float] = {}
        snapshot_intensity = 0.0
        try:
            state = await self._states.get_current(session, user_id, companion_id)
            emotion = EmotionState.model_validate(state.emotion)
            primary = emotion.primary
            secondary = list(emotion.secondary)
            levels = {key: float(value) for key, value in emotion.levels.items()}
            snapshot_intensity = float(emotion.intensity)
        except NotFoundError:
            logger.info("state missing for companion %s; using calm expression", companion_id)
        except Exception:
            logger.exception("failed to load emotion for TTS; falling back to calm")

        return self._expression.build(
            primary=primary,
            secondary=secondary,
            levels=levels,
            snapshot_intensity=snapshot_intensity,
            voice_expression=voice_profile,
        )

    def _store_asset_file(self, companion_id: uuid.UUID, task_id: uuid.UUID, source: Path) -> Path:
        root = Path(self._settings.audio_storage_dir) / "generated" / str(companion_id)
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{task_id}.wav"
        shutil.copyfile(source, target)
        return target

    async def _fail_task(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        companion_id: uuid.UUID,
        exc: Exception,
    ) -> None:
        async with session.begin():
            locked = await self._tasks.get(session, task_id, companion_id)
            if locked is None:
                return
            locked.task_status = AudioTaskStatus.FAILED.value
            locked.completed_at = datetime.now(UTC)
            locked.error_code = getattr(exc, "code", "audio_worker_error")
            locked.error_message = str(exc) or type(exc).__name__
            await session.flush()

    async def _log_call(
        self,
        task_type: ModelTaskType,
        trace_id: uuid.UUID,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        started_at: datetime,
        *,
        ok: bool,
        latency_ms: int,
        model_name: str,
        error: str | None = None,
    ) -> None:
        completed_at = datetime.now(UTC)
        if completed_at < started_at:
            completed_at = started_at
        request = RecordModelCallRequest(
            user_id=user_id,
            companion_id=companion_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            task_type=task_type,
            provider=ModelProvider.LOCAL,
            model_name=model_name,
            status=ModelCallStatus.SUCCESS if ok else ModelCallStatus.FAILED,
            latency_ms=max(0, latency_ms),
            error_message=None if ok else (error or "音频推理失败"),
            created_at=started_at,
            completed_at=completed_at,
        )
        try:
            async with self._session_factory() as log_session:
                await self._logs.record(log_session, request)
        except Exception:
            logger.exception("failed to record audio model call log")


def _tts_cache_reusable(expression_json: object) -> bool:
    """旧契约（中文 instruct / 决策摘要）缓存一律作废，避免继续念出决策内容。"""
    if not isinstance(expression_json, dict):
        return False
    version = expression_json.get("contract_version")
    return version == TTS_CONTRACT_VERSION


def _latency(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _asset_url(user_id: uuid.UUID, companion_id: uuid.UUID, asset_id: uuid.UUID) -> str:
    return f"/api/audio/users/{user_id}/companions/{companion_id}/assets/{asset_id}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _task_response(task: AudioTask) -> AudioTaskResponse:
    return AudioTaskResponse(
        id=task.id,
        companion_id=task.companion_id,
        task_type=AudioTaskType(task.task_type),
        task_status=AudioTaskStatus(task.task_status),
        message_id=task.message_id,
        turn_id=task.turn_id,
        error_code=task.error_code,
        error_message=task.error_message,
        duration_ms=task.duration_ms,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )
