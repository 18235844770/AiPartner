"""为正式记忆版本生成本地向量。失败只记录向量状态，不回滚记忆。"""

import hashlib
import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings, get_settings
from app.modules.infrastructure.domain.enums import ModelConfigKey
from app.modules.infrastructure.services.model_config_service import ModelConfigService
from app.modules.memory.domain.enums import EmbeddingStatus
from app.modules.memory.services.memory_service import MemoryService
from app.modules.model_adapter.domain.embedding import EmbeddingResult
from app.modules.model_adapter.domain.errors import ModelAdapterError
from app.modules.model_adapter.services.model_adapter import ModelCallScope
from app.shared.database.session import get_session_factory

logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    async def embed(self, task: ModelConfigKey, texts: list[str], scope: ModelCallScope) -> EmbeddingResult: ...


class MemoryEmbeddingService:
    def __init__(
        self,
        memories: MemoryService | None = None,
        adapter: EmbeddingClient | None = None,
        configs: ModelConfigService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._memories = memories or MemoryService()
        self._adapter = adapter or _default_adapter()
        self._configs = configs or ModelConfigService()
        self._session_factory = session_factory or get_session_factory()
        self._settings = settings or get_settings()

    async def embed_version(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        version_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> dict[str, object]:
        _memory, version = await self._memories.require_version(
            session, user_id, companion_id, memory_id, version_id
        )
        config = await self._configs.ensure_local_embedding(self._settings.embedding_model_name)
        model_name = config.model_name
        if len(model_name) > 64:
            raise ModelAdapterError("Embedding 模型名称过长")
        digest = hashlib.sha256(version.content.encode("utf-8")).hexdigest()
        existing = await self._memories.find_embedding(session, version.id, model_name)
        if (
            existing is not None
            and existing.status == EmbeddingStatus.COMPLETED.value
            and existing.content_hash == digest
            and existing.embedding is not None
        ):
            return {"status": "completed", "memory_id": str(memory_id), "skipped": True}
        try:
            result = await self._adapter.embed(
                ModelConfigKey.EMBEDDING,
                [version.content],
                ModelCallScope(
                    trace_id=uuid.uuid4(),
                    user_id=user_id,
                    companion_id=companion_id,
                    background_task_id=task_id,
                ),
            )
        except ModelAdapterError:
            await self._mark_failed(user_id, companion_id, memory_id, version_id, model_name)
            raise
        if result.model_name != model_name or len(result.vectors) != 1:
            await self._mark_failed(user_id, companion_id, memory_id, version_id, model_name)
            raise ModelAdapterError("Embedding 模型与配置不一致")
        await self._memories.store_embedding(
            session,
            user_id,
            companion_id,
            memory_id,
            version_id,
            embedding_model=model_name,
            status=EmbeddingStatus.COMPLETED,
            embedding=result.vectors[0],
        )
        return {"status": "completed", "memory_id": str(memory_id), "skipped": False}

    async def _mark_failed(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        memory_id: uuid.UUID,
        version_id: uuid.UUID,
        model_name: str,
    ) -> None:
        try:
            async with self._session_factory() as extra:
                await self._memories.store_embedding(
                    extra,
                    user_id,
                    companion_id,
                    memory_id,
                    version_id,
                    embedding_model=model_name,
                    status=EmbeddingStatus.FAILED,
                    embedding=None,
                )
        except Exception:
            logger.exception("failed to record embedding failure for version %s", version_id)


def _default_adapter() -> EmbeddingClient:
    from app.modules.model_adapter.services.model_adapter import ModelAdapter

    return ModelAdapter()
