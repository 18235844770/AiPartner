import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.infrastructure.api.schemas import (
    AddModelConfigVersionRequest,
    CreateModelConfigRequest,
    ModelConfigResponse,
    RollbackModelConfigRequest,
)
from app.modules.infrastructure.domain.enums import CONFIG_TASK_TYPES, ModelConfigKey, ModelProvider, ModelTaskType
from app.modules.infrastructure.repositories.infrastructure_repository import ModelConfigRepository
from app.modules.infrastructure.repositories.models import ModelConfig
from app.shared.database.session import get_session_factory
from app.shared.exceptions.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


class ModelConfigService:
    def __init__(
        self,
        configs: ModelConfigRepository | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._configs = configs or ModelConfigRepository()
        self._session_factory = session_factory or get_session_factory()

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

    async def ensure_local_embedding(self, model_name: str) -> ModelConfig:
        """没有 Embedding 配置时补一条本地默认配置。已有配置保持不变，并先提交，供适配器读取。"""
        try:
            created = await self._insert_local_embedding(model_name)
        except IntegrityError:
            logger.info("local embedding config was created concurrently")
            created = None
        if created is not None:
            return created
        current = await self._read_embedding_config()
        if current is None:
            raise NotFoundError("模型配置不存在")
        return current

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

    async def _insert_local_embedding(self, model_name: str) -> ModelConfig | None:
        async with self._session_factory() as session:
            async with session.begin():
                current = await self._configs.get_default(session, ModelTaskType.EMBEDDING.value)
                if current is not None:
                    return current
                existing = await self._configs.lock_latest(session, ModelConfigKey.EMBEDDING.value)
                if existing is not None:
                    return existing
                now = datetime.now(UTC)
                data = CreateModelConfigRequest(
                    config_key=ModelConfigKey.EMBEDDING,
                    model_name=model_name,
                    is_enabled=True,
                    is_default=True,
                )
                config = self._new_row(ModelConfigKey.EMBEDDING, data, version=1, now=now)
                await self._replace_default(session, config)
                await self._configs.add(session, config)
                return config

    async def _read_embedding_config(self) -> ModelConfig | None:
        async with self._session_factory() as session:
            async with session.begin():
                current = await self._configs.get_default(session, ModelTaskType.EMBEDDING.value)
                if current is not None:
                    return current
                return await self._configs.lock_latest(session, ModelConfigKey.EMBEDDING.value)

    def _new_row(
        self,
        config_key: ModelConfigKey,
        data: CreateModelConfigRequest | AddModelConfigVersionRequest,
        version: int,
        now: datetime,
    ) -> ModelConfig:
        return ModelConfig(
            config_key=config_key.value,
            provider=(
                ModelProvider.LOCAL.value
                if config_key == ModelConfigKey.EMBEDDING
                else ModelProvider.DEEPSEEK.value
            ),
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
