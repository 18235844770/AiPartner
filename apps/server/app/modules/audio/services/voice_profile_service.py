"""陪伴者音色配置。Phase 3 提供默认 stub 音色，供固定音色合成。"""

from __future__ import annotations

import hashlib
import struct
import uuid
import wave
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.modules.audio.domain.enums import AudioEngine
from app.modules.audio.domain.schemas import VoiceProfileResponse
from app.modules.audio.repositories.audio_repository import VoiceProfileRepository
from app.modules.audio.repositories.models import CompanionVoiceProfile
from app.modules.identity.services.identity_service import IdentityService

# 与 CosyVoice 官方 zero_shot_prompt.wav 文案一致；占位句会被模型念出，禁止再用。
_OFFICIAL_REFERENCE_TEXT = "希望你以后能够做的比我还好呦。"
_PLACEHOLDER_REFERENCE_TEXT = "这是默认参考音频对应的文字。"


class VoiceProfileService:
    def __init__(
        self,
        voices: VoiceProfileRepository | None = None,
        identity: IdentityService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._voices = voices or VoiceProfileRepository()
        self._identity = identity or IdentityService()
        self._settings = settings or get_settings()

    async def list_voices(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> list[CompanionVoiceProfile]:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            return await self._voices.list_for_companion(session, companion_id)

    async def ensure_default(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> CompanionVoiceProfile:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            existing = await self._voices.get_default(session, companion_id)
            if existing is not None:
                if existing.reference_text.strip() in {
                    _PLACEHOLDER_REFERENCE_TEXT,
                    _PLACEHOLDER_REFERENCE_TEXT.rstrip("。"),
                } or "默认参考音频" in existing.reference_text:
                    existing.reference_text = _OFFICIAL_REFERENCE_TEXT
                    existing.updated_at = datetime.now(UTC)
                return existing
            now = datetime.now(UTC)
            reference = self._ensure_stub_reference(companion_id)
            checksum = _sha256_file(reference)
            profile = CompanionVoiceProfile(
                companion_id=companion_id,
                voice_name="默认音色",
                engine=AudioEngine.STUB.value,
                model_name=self._settings.tts_model_name,
                reference_audio_path=str(reference),
                reference_text=_OFFICIAL_REFERENCE_TEXT,
                reference_checksum=checksum,
                language="zh",
                default_speed=1.0,
                is_default=True,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            await self._voices.add(session, profile)
            return profile

    def _ensure_stub_reference(self, companion_id: uuid.UUID) -> Path:
        root = Path(self._settings.audio_storage_dir) / "voices" / str(companion_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "reference_stub.wav"
        if path.exists():
            return path
        frames = 16000
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))
        return path


def to_voice_response(profile: CompanionVoiceProfile) -> VoiceProfileResponse:
    return VoiceProfileResponse(
        id=profile.id,
        companion_id=profile.companion_id,
        voice_name=profile.voice_name,
        engine=profile.engine,
        model_name=profile.model_name,
        language=profile.language,
        default_speed=profile.default_speed,
        is_default=profile.is_default,
        enabled=profile.enabled,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
