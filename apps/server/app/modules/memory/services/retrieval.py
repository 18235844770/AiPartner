"""混合检索。资格先于排序；向量不可用时，关键词、时间和关系仍然返回。"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.domain.enums import ModelConfigKey
from app.modules.memory.domain.enums import MemorySourceRole, MemorySourceType
from app.modules.memory.domain.retrieval import (
    RETRIEVAL_LIMIT,
    cosine_similarity,
    episodic_in_window,
    query_time_window,
    retrieval_allowed,
    retrieval_context,
    retrieval_score,
    source_is_reliable,
    topic_related,
    vector_matches,
)
from app.modules.memory.repositories.memory_repository import MemoryRepository
from app.modules.memory.repositories.models import Memory, MemorySource, MemoryVersion
from app.modules.memory.services.memory_service import MemoryService
from app.modules.model_adapter.domain.embedding import EmbeddingResult
from app.modules.model_adapter.domain.errors import ModelAdapterError
from app.modules.model_adapter.services.model_adapter import ModelCallScope
from app.shared.exceptions.errors import NotFoundError

logger = logging.getLogger(__name__)


class QueryEmbedder(Protocol):
    async def embed(self, task: ModelConfigKey, texts: list[str], scope: ModelCallScope) -> EmbeddingResult: ...


class MemoryRetrievalService:
    def __init__(
        self,
        memories: MemoryService | None = None,
        repository: MemoryRepository | None = None,
        embedder: QueryEmbedder | None = None,
    ) -> None:
        self._memories = memories or MemoryService()
        self._repository = repository or MemoryRepository()
        self._embedder = embedder

    async def retrieve(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        query: str,
        *,
        include_archived: bool = False,
        limit: int = RETRIEVAL_LIMIT,
    ) -> list[dict[str, object]]:
        if session.in_transaction():
            return await self._retrieve(
                session, user_id, companion_id, query, include_archived=include_archived, limit=limit
            )
        async with session.begin():
            return await self._retrieve(
                session, user_id, companion_id, query, include_archived=include_archived, limit=limit
            )

    async def _retrieve(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        query: str,
        *,
        include_archived: bool,
        limit: int,
    ) -> list[dict[str, object]]:
        rows = await self._memories.list_memories(session, user_id, companion_id)
        now = datetime.now(UTC)
        window = query_time_window(query, now)
        vectors = await self._vectors(session, rows, user_id, companion_id, query)
        neighbors = _neighbors(await self._repository.list_relation_pairs(session, companion_id))
        prepared = [
            _prepare(memory, version, sources, query, now, window, vectors, include_archived)
            for memory, version, sources in rows
        ]
        seeds = {item.memory_id for item in prepared if item.seed}
        ranked: list[tuple[Decimal, int, datetime, dict[str, object]]] = []
        for item in prepared:
            relation = item.memory_id not in seeds and _linked(item.memory_id, seeds, neighbors)
            allowed = item.allowed or (
                relation
                and retrieval_allowed(
                    memory_type=item.memory_type,
                    status=item.status,
                    origin=item.origin,
                    is_inference=item.is_inference,
                    content=item.content,
                    valid_from=item.valid_from,
                    valid_until=item.valid_until,
                    has_message_evidence=item.evidence,
                    query=query,
                    subject=item.subject,
                    summary=item.summary,
                    category=item.category,
                    now=now,
                    include_archived=include_archived,
                    relation_match=True,
                )
            )
            if not allowed:
                continue
            strength = int(item.keyword) + int(item.vector) + int(item.time_match) + int(relation)
            score = retrieval_score(
                related=item.keyword,
                confidence=item.confidence,
                reliable=source_is_reliable(
                    origin=item.origin,
                    is_inference=item.is_inference,
                    has_message_evidence=item.evidence,
                ),
                status=item.status,
                importance=item.importance,
            )
            ranked.append((score, strength, item.updated_at, item.context))
        ranked.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
        return [entry[3] for entry in ranked[:limit]]

    async def _vectors(
        self,
        session: AsyncSession,
        rows: list[tuple[Memory, MemoryVersion, list[MemorySource]]],
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        query: str,
    ) -> dict[uuid.UUID, float]:
        if not query.strip() or not rows:
            return {}
        by_version = {version.id: (memory.id, version.content) for memory, version, _sources in rows}
        stored = await self._repository.list_completed_embeddings(session, list(by_version))
        usable: list[tuple[uuid.UUID, list[float], str]] = []
        for embedding in stored:
            memory_id, content = by_version.get(embedding.memory_version_id, (None, None))
            values = _vector_values(embedding.embedding)
            if memory_id is None or content is None or values is None:
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if embedding.content_hash != digest:
                continue
            usable.append((memory_id, values, embedding.embedding_model))
        if not usable:
            return {}
        embedded = await self._embed_query(user_id, companion_id, query.strip())
        if embedded is None:
            return {}
        model_name, query_vector = embedded
        scores: dict[uuid.UUID, float] = {}
        for memory_id, values, embedding_model in usable:
            if embedding_model != model_name:
                continue
            scores[memory_id] = cosine_similarity(query_vector, values)
        return scores

    async def _embed_query(
        self,
        user_id: uuid.UUID,
        companion_id: uuid.UUID,
        query: str,
    ) -> tuple[str, list[float]] | None:
        try:
            result = await self._query_embedder().embed(
                ModelConfigKey.EMBEDDING,
                [query],
                ModelCallScope(trace_id=uuid.uuid4(), user_id=user_id, companion_id=companion_id),
            )
        except (ModelAdapterError, NotFoundError):
            logger.warning("query embedding unavailable; keyword, time and relation retrieval continue")
            return None
        if len(result.vectors) != 1:
            return None
        values = _vector_values(result.vectors[0])
        if values is None:
            return None
        return result.model_name, values

    def _query_embedder(self) -> QueryEmbedder:
        if self._embedder is not None:
            return self._embedder
        from app.modules.model_adapter.services.model_adapter import ModelAdapter

        self._embedder = ModelAdapter()
        return self._embedder


class _Prepared:
    def __init__(
        self,
        *,
        memory_id: uuid.UUID,
        memory_type: str,
        status: str,
        origin: str,
        is_inference: bool,
        content: str,
        subject: str | None,
        summary: str | None,
        category: str,
        evidence: bool,
        valid_from: datetime | None,
        valid_until: datetime | None,
        confidence: Decimal,
        importance: int,
        updated_at: datetime,
        keyword: bool,
        vector: bool,
        time_match: bool,
        allowed: bool,
        seed: bool,
        context: dict[str, object],
    ) -> None:
        self.memory_id = memory_id
        self.memory_type = memory_type
        self.status = status
        self.origin = origin
        self.is_inference = is_inference
        self.content = content
        self.subject = subject
        self.summary = summary
        self.category = category
        self.evidence = evidence
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.confidence = confidence
        self.importance = importance
        self.updated_at = updated_at
        self.keyword = keyword
        self.vector = vector
        self.time_match = time_match
        self.allowed = allowed
        self.seed = seed
        self.context = context


def _prepare(
    memory: Memory,
    version: MemoryVersion,
    sources: list[MemorySource],
    query: str,
    now: datetime,
    window: tuple[datetime, datetime] | None,
    vectors: dict[uuid.UUID, float],
    include_archived: bool,
) -> _Prepared:
    evidence = _has_message_evidence(sources)
    keyword = topic_related(query, version.content, version.summary, memory.subject, memory.memory_category)
    similarity = vectors.get(memory.id, 0.0)
    vector = vector_matches(similarity)
    time_match = episodic_in_window(memory.memory_type, memory.valid_from or memory.created_at, window)
    allowed = retrieval_allowed(
        memory_type=memory.memory_type,
        status=memory.status,
        origin=memory.memory_origin,
        is_inference=memory.is_inference,
        content=version.content,
        valid_from=memory.valid_from,
        valid_until=memory.valid_until,
        has_message_evidence=evidence,
        query=query,
        subject=memory.subject,
        summary=version.summary,
        category=memory.memory_category,
        now=now,
        include_archived=include_archived,
        vector_match=vector,
        time_match=time_match,
    )
    return _Prepared(
        memory_id=memory.id,
        memory_type=memory.memory_type,
        status=memory.status,
        origin=memory.memory_origin,
        is_inference=memory.is_inference,
        content=version.content,
        subject=memory.subject,
        summary=version.summary,
        category=memory.memory_category,
        evidence=evidence,
        valid_from=memory.valid_from,
        valid_until=memory.valid_until,
        confidence=memory.confidence,
        importance=memory.importance,
        updated_at=memory.updated_at,
        keyword=keyword,
        vector=vector,
        time_match=time_match,
        allowed=allowed,
        seed=allowed and (keyword or vector or time_match),
        context=retrieval_context(
            memory_id=memory.id,
            memory_type=memory.memory_type,
            memory_status=memory.status,
            content=version.content,
            confidence=memory.confidence,
            is_inference=memory.is_inference,
            origin=memory.memory_origin,
            source_count=len(sources),
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
        ),
    )


def _neighbors(pairs: list[tuple[uuid.UUID, uuid.UUID]]) -> dict[uuid.UUID, set[uuid.UUID]]:
    linked: dict[uuid.UUID, set[uuid.UUID]] = {}
    for source_id, target_id in pairs:
        linked.setdefault(source_id, set()).add(target_id)
        linked.setdefault(target_id, set()).add(source_id)
    return linked


def _linked(memory_id: uuid.UUID, seeds: set[uuid.UUID], neighbors: dict[uuid.UUID, set[uuid.UUID]]) -> bool:
    return any(other in seeds for other in neighbors.get(memory_id, ()))


def _vector_values(value: object) -> list[float] | None:
    if value is None or isinstance(value, str | bytes):
        return None
    try:
        values = [float(item) for item in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return None
    if not values:
        return None
    return values


def _has_message_evidence(sources: list[MemorySource]) -> bool:
    return any(
        source.source_type == MemorySourceType.MESSAGE.value
        and source.message_id is not None
        and source.source_role in {MemorySourceRole.EVIDENCE.value, MemorySourceRole.CORRECTION.value}
        for source in sources
    )
