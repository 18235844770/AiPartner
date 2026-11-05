import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.memory.domain.enums import MemorySourceRole, MemorySourceType
from app.modules.memory.domain.retrieval import (
    RETRIEVAL_LIMIT,
    retrieval_allowed,
    retrieval_context,
    retrieval_score,
    source_is_reliable,
    topic_related,
)
from app.modules.memory.repositories.models import MemorySource
from app.modules.memory.services.memory_service import MemoryService


class MemoryRetrievalService:
    def __init__(self, memories: MemoryService | None = None) -> None:
        self._memories = memories or MemoryService()

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
        rows = await self._memories.list_memories(session, user_id, companion_id)
        now = datetime.now(UTC)
        ranked: list[tuple[object, datetime, dict[str, object]]] = []
        for memory, version, sources in rows:
            evidence = _has_message_evidence(sources)
            allowed = retrieval_allowed(
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
            )
            if not allowed:
                continue
            related = topic_related(query, version.content, version.summary, memory.subject, memory.memory_category)
            score = retrieval_score(
                related=related,
                confidence=memory.confidence,
                reliable=source_is_reliable(
                    origin=memory.memory_origin,
                    is_inference=memory.is_inference,
                    has_message_evidence=evidence,
                ),
                status=memory.status,
                importance=memory.importance,
            )
            ranked.append(
                (
                    score,
                    memory.updated_at,
                    retrieval_context(
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
            )
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]]


def _has_message_evidence(sources: list[MemorySource]) -> bool:
    return any(
        source.source_type == MemorySourceType.MESSAGE.value
        and source.message_id is not None
        and source.source_role in {MemorySourceRole.EVIDENCE.value, MemorySourceRole.CORRECTION.value}
        for source in sources
    )
