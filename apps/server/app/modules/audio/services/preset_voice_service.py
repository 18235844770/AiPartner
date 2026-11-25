"""陪伴者当前音色。没有记录时用目录里的默认音色。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audio.domain.preset_voices import (
    PresetVoice,
    get_preset,
    load_preset_catalog,
    resolve_stored_preset,
)
from app.modules.audio.domain.schemas import VoicePresetResponse, VoicePresetSelectionResponse
from app.modules.audio.repositories.audio_repository import VoicePresetRepository
from app.modules.audio.repositories.models import CompanionVoicePreset
from app.modules.identity.services.identity_service import IdentityService
from app.shared.exceptions.errors import NotFoundError


def to_preset_response(preset: PresetVoice) -> VoicePresetResponse:
    return VoicePresetResponse(
        id=preset.id,
        name=preset.name,
        provider=preset.provider,
        provider_label=preset.provider_label,
        model=preset.model,
        language=preset.language,
    )


class PresetVoiceService:
    def __init__(
        self,
        presets: VoicePresetRepository | None = None,
        identity: IdentityService | None = None,
    ) -> None:
        self._presets = presets or VoicePresetRepository()
        self._identity = identity or IdentityService()

    def list_catalog(self) -> list[VoicePresetResponse]:
        return [to_preset_response(item) for item in load_preset_catalog().voices]

    async def get_selection(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> VoicePresetSelectionResponse:
        preset = await self.selected_preset(session, user_id, companion_id)
        if preset is None:
            return VoicePresetSelectionResponse(preset_id=None, preset=None)
        return VoicePresetSelectionResponse(preset_id=preset.id, preset=to_preset_response(preset))

    async def selected_preset(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> PresetVoice | None:
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            row = await self._presets.get(session, companion_id)
        stored = None if row is None else row.preset_id
        return resolve_stored_preset(stored)

    async def set_selection(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        preset_id: str | None,
    ) -> VoicePresetSelectionResponse:
        if preset_id:
            preset = get_preset(preset_id)
            if preset is None:
                raise NotFoundError("音色不存在")
        else:
            preset = resolve_stored_preset(None)
            if preset is None:
                raise NotFoundError("音色不存在")
        async with session.begin():
            await self._identity.get_owned_companion(session, user_id, companion_id)
            await self._presets.upsert(
                session,
                CompanionVoicePreset(
                    companion_id=companion_id,
                    preset_id=preset.id,
                    updated_at=datetime.now(UTC),
                ),
            )
        return VoicePresetSelectionResponse(preset_id=preset.id, preset=to_preset_response(preset))
