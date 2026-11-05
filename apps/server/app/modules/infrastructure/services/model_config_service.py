import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.api.schemas import (
    AddModelConfigVersionRequest,
    CreateModelConfigRequest,
    ModelConfigResponse,
    RollbackModelConfigRequest,
)
from app.modules.infrastructure.domain.enums import CONFIG_TASK_TYPES, ModelConfigKey, ModelProvider, ModelTaskType
from app.modules.infrastructure.repositories.infrastructure_repository import ModelConfigRepository
from app.modules.infrastructure.repositories.models import ModelConfig
from app.shared.exceptions.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


class ModelConfigService:
    def __init__(self, configs: ModelConfigRepository | None = None) -> None:
        self._configs = configs or ModelConfigRepository()

    async def create(self, session: AsyncSession, data: CreateModelConfigRequest) -> ModelConfig:
        async with session.begin():
            existing = await self._configs.lock_latest(session, data.config_key.value)
            if existing is not None:
                raise ConflictError("配置已经存在")
            now = datetime.now(UTC)
            config = self._new_row(data.config_key, data, version=1, now=now)
            await self._replace_default(session, config)
            await self._configs.add(session, config)
        logger.info("created model config %s version 1", config.config_key)
        return config

    async def add_version(
        self,
        session: AsyncSession,
        config_key: ModelConfigKey,
        data: AddModelConfigVersionRequest,
    ) -> ModelConfig:
        async with session.begin():
            latest = await self._configs.lock_latest(session, config_key.value)
            if latest is None:
                raise NotFoundError("配置不存在")
            now = datetime.now(UTC)
            config = self._new_row(config_key, data, version=latest.version + 1, now=now)
            await self._replace_default(session, config)
            await self._configs.add(session, config)
        logger.info("added model config %s version %s", config.config_key, config.version)
        return config

    async def rollback(
        self,
        session: AsyncSession,
        config_key: ModelConfigKey,
        data: RollbackModelConfigRequest,
    ) -> ModelConfig:
        async with session.begin():
            target = await self._configs.lock_version(session, config_key.value, data.version)
            if target is None:
                raise NotFoundError("配置版本不存在")
            if target.is_enabled and target.is_default:
                raise ConflictError("已经是当前配置")
            now = datetime.now(UTC)
            current = await self._configs.lock_default(session, target.task_type)
            if current is not None and current.id != target.id:
                current.is_default = False
                current.updated_at = now
                await session.flush()
            target.is_enabled = True
            target.is_default = True
            target.updated_at = now
        logger.info("rolled back model config %s to version %s", config_key.value, target.version)
        return target

    async def list_configs(self, session: AsyncSession) -> list[ModelConfig]:
        async with session.begin():
            return await self._configs.list_all(session)

    async def _replace_default(self, session: AsyncSession, config: ModelConfig) -> None:
        if not config.is_default or not config.is_enabled:
            return
        current = await self._configs.lock_default(session, config.task_type)
        if current is None:
            return
        current.is_default = False
        current.updated_at = config.updated_at
        await session.flush()

    def _new_row(
        self,
        config_key: ModelConfigKey,
        data: CreateModelConfigRequest | AddModelConfigVersionRequest,
        version: int,
        now: datetime,
    ) -> ModelConfig:
        return ModelConfig(
            config_key=config_key.value,
            provider=ModelProvider.DEEPSEEK.value,
            model_name=data.model_name,
            task_type=CONFIG_TASK_TYPES[config_key].value,
            parameters=data.parameters,
            is_enabled=data.is_enabled,
            is_default=data.is_default,
            version=version,
            created_at=now,
            updated_at=now,
        )


def to_config_response(config: ModelConfig) -> ModelConfigResponse:
    return ModelConfigResponse(
        id=config.id,
        config_key=ModelConfigKey(config.config_key),
        provider=ModelProvider(config.provider),
        model_name=config.model_name,
        task_type=ModelTaskType(config.task_type),
        parameters=config.parameters,
        is_enabled=config.is_enabled,
        is_default=config.is_default,
        version=config.version,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )
