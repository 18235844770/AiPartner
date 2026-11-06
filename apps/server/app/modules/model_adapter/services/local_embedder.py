"""本地 BGE-M3。权重只在真正生成向量时加载，测试注入替身，不下载模型。"""

import asyncio

from app.modules.model_adapter.domain.embedding import EMBEDDING_DIMENSIONS, LOCAL_EMBEDDING_MODEL
from app.modules.model_adapter.domain.errors import ModelCapabilityError, ModelOutputError


class FastEmbedBackend:
    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    async def embed(self, model_name: str, texts: list[str]) -> list[list[float]]:
        if model_name != LOCAL_EMBEDDING_MODEL:
            raise ModelCapabilityError("当前本地 Embedding 只支持 BAAI/bge-m3")
        return await asyncio.to_thread(self._embed, model_name, texts)

    def _embed(self, model_name: str, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding

        model = self._models.get(model_name)
        if model is None:
            model = TextEmbedding(model_name=model_name)
            self._models[model_name] = model
        rows = [[float(item) for item in vector] for vector in model.embed(texts)]
        if len(rows) != len(texts) or any(len(vector) != EMBEDDING_DIMENSIONS for vector in rows):
            raise ModelOutputError("向量维度不正确")
        return rows
