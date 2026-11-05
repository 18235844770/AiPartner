import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.domain.enums import BackgroundTaskStatus
from app.modules.infrastructure.repositories.models import BackgroundTask, ModelCallLog, ModelConfig


class ModelConfigRepository:
    async def add(self, session: AsyncSession, config: ModelConfig) -> ModelConfig:
        session.add(config)
        await session.flush()
        return config

    async def get(self, session: AsyncSession, config_id: uuid.UUID) -> ModelConfig | None:
        return await session.get(ModelConfig, config_id)

    async def list_all(self, session: AsyncSession) -> list[ModelConfig]:
        statement = select(ModelConfig).order_by(ModelConfig.config_key.asc(), ModelConfig.version.desc())
        return list((await session.execute(statement)).scalars().all())

    async def lock_latest(self, session: AsyncSession, config_key: str) -> ModelConfig | None:
        statement = (
            select(ModelConfig)
            .where(ModelConfig.config_key == config_key)
            .order_by(ModelConfig.version.desc())
            .limit(1)
            .with_for_update()
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def lock_version(self, session: AsyncSession, config_key: str, version: int) -> ModelConfig | None:
        statement = (
            select(ModelConfig)
            .where(ModelConfig.config_key == config_key, ModelConfig.version == version)
            .with_for_update()
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def get_default(self, session: AsyncSession, task_type: str) -> ModelConfig | None:
        statement = select(ModelConfig).where(
            ModelConfig.task_type == task_type,
            ModelConfig.is_enabled.is_(True),
            ModelConfig.is_default.is_(True),
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def lock_default(self, session: AsyncSession, task_type: str) -> ModelConfig | None:
        statement = (
            select(ModelConfig)
            .where(
                ModelConfig.task_type == task_type,
                ModelConfig.is_enabled.is_(True),
                ModelConfig.is_default.is_(True),
            )
            .with_for_update()
        )
        return (await session.execute(statement)).scalar_one_or_none()


class BackgroundTaskRepository:
    async def add(self, session: AsyncSession, task: BackgroundTask) -> BackgroundTask:
        session.add(task)
        await session.flush()
        return task

    async def get(self, session: AsyncSession, task_id: uuid.UUID) -> BackgroundTask | None:
        return await session.get(BackgroundTask, task_id)

    async def lock(self, session: AsyncSession, task_id: uuid.UUID) -> BackgroundTask | None:
        statement = select(BackgroundTask).where(BackgroundTask.id == task_id).with_for_update()
        return (await session.execute(statement)).scalar_one_or_none()

    async def lock_by_key(self, session: AsyncSession, task_key: str) -> BackgroundTask | None:
        statement = select(BackgroundTask).where(BackgroundTask.task_key == task_key).with_for_update()
        return (await session.execute(statement)).scalar_one_or_none()

    async def list_due_ids(self, session: AsyncSession, now: datetime, limit: int) -> list[uuid.UUID]:
        statement = (
            select(BackgroundTask.id)
            .where(
                BackgroundTask.status.in_(
                    (BackgroundTaskStatus.PENDING.value, BackgroundTaskStatus.RETRYING.value)
                ),
                BackgroundTask.dispatched_at.is_(None),
                BackgroundTask.scheduled_at <= now,
            )
            .order_by(BackgroundTask.scheduled_at.asc(), BackgroundTask.created_at.asc())
            .limit(limit)
        )
        return list((await session.execute(statement)).scalars().all())


class ModelCallLogRepository:
    async def add(self, session: AsyncSession, log: ModelCallLog) -> ModelCallLog:
        session.add(log)
        await session.flush()
        return log

    async def list_by_trace(self, session: AsyncSession, trace_id: uuid.UUID) -> list[ModelCallLog]:
        statement = (
            select(ModelCallLog)
            .where(ModelCallLog.trace_id == trace_id)
            .order_by(ModelCallLog.created_at.asc())
        )
        return list((await session.execute(statement)).scalars().all())
