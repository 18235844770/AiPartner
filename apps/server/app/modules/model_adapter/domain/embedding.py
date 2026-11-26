"""本地 Embedding。第一版只验证 BGE-M3，维度 1024。"""

from dataclasses import dataclass
from typing import Protocol

EMBEDDING_DIMENSIONS = 1024
LOCAL_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B-Q"


class TextEmbedder(Protocol):
    async def embed(self, model_name: str, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingResult:
    model_name: str
    vectors: list[list[float]]

