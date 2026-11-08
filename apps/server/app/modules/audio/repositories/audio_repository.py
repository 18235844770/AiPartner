import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audio.repositories.models import AudioAsset, AudioTask, CompanionVoiceProfile


class VoiceProfileRepository:
    async def list_for_companion(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
    ) -> list[CompanionVoiceProfile]:
        result = await session.execute(
            select(CompanionVoiceProfile)
            .where(CompanionVoiceProfile.companion_id == companion_id)
            .order_by(CompanionVoiceProfile.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(
        self,
        session: AsyncSession,
        voice_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> CompanionVoiceProfile | None:
        result = await session.execute(
            select(CompanionVoiceProfile).where(
                CompanionVoiceProfile.id == voice_id,
                CompanionVoiceProfile.companion_id == companion_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_default(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
    ) -> CompanionVoiceProfile | None:
        result = await session.execute(
            select(CompanionVoiceProfile).where(
                CompanionVoiceProfile.companion_id == companion_id,
                CompanionVoiceProfile.is_default.is_(True),
                CompanionVoiceProfile.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def add(self, session: AsyncSession, profile: CompanionVoiceProfile) -> None:
        session.add(profile)
        await session.flush()


class AudioTaskRepository:
    async def add(self, session: AsyncSession, task: AudioTask) -> None:
        session.add(task)
        await session.flush()

    async def get(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> AudioTask | None:
        result = await session.execute(
            select(AudioTask).where(AudioTask.id == task_id, AudioTask.companion_id == companion_id)
        )
        return result.scalar_one_or_none()

    async def get_completed_tts_for_message(
        self,
        session: AsyncSession,
        companion_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> AudioTask | None:
        result = await session.execute(
            select(AudioTask)
            .where(
                AudioTask.companion_id == companion_id,
                AudioTask.message_id == message_id,
                AudioTask.task_type == "tts",
                AudioTask.task_status == "completed",
            )
            .order_by(AudioTask.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark(
        self,
        session: AsyncSession,
        task: AudioTask,
        *,
        status: str,
        completed_at: datetime | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
        model_name: str | None = None,
    ) -> None:
        task.task_status = status
        task.completed_at = completed_at
        task.error_code = error_code
        task.error_message = error_message
        if duration_ms is not None:
            task.duration_ms = duration_ms
        if model_name is not None:
            task.model_name = model_name
        await session.flush()


class AudioAssetRepository:
    async def add(self, session: AsyncSession, asset: AudioAsset) -> None:
        session.add(asset)
        await session.flush()

    async def get(
        self,
        session: AsyncSession,
        asset_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> AudioAsset | None:
        result = await session.execute(
            select(AudioAsset).where(AudioAsset.id == asset_id, AudioAsset.companion_id == companion_id)
        )
        return result.scalar_one_or_none()

    async def get_by_task(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        companion_id: uuid.UUID,
    ) -> AudioAsset | None:
        result = await session.execute(
            select(AudioAsset).where(
                AudioAsset.audio_task_id == task_id,
                AudioAsset.companion_id == companion_id,
            )
        )
        return result.scalar_one_or_none()
