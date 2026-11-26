"""Load the supported local model once per process, on demand."""

import asyncio
from functools import lru_cache
from threading import Lock

from app.modules.model_adapter.domain.embedding import EMBEDDING_DIMENSIONS, LOCAL_EMBEDDING_MODEL
from app.modules.model_adapter.domain.errors import ModelAdapterError, ModelCapabilityError, ModelOutputError


_load_lock = Lock()


@lru_cache(maxsize=1)
def _load_model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=LOCAL_EMBEDDING_MODEL, threads=2)


class FastEmbedBackend:

    async def embed(self, model_name: str, texts: list[str]) -> list[list[float]]:
        if model_name != LOCAL_EMBEDDING_MODEL:
            raise ModelCapabilityError(f"当前本地 Embedding 只支持 {LOCAL_EMBEDDING_MODEL}")
        return await asyncio.to_thread(self._embed, texts)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            with _load_lock:
                model = _load_model()
            rows = [[float(item) for item in vector] for vector in model.embed(texts)]
        except Exception as exc:
            raise ModelAdapterError("本地向量模型暂不可用") from exc
        if len(rows) != len(texts) or any(len(vector) != EMBEDDING_DIMENSIONS for vector in rows):
            raise ModelOutputError("向量维度不正确")
        return rows
