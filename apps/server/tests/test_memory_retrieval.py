import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.memory.domain.retrieval import (
    cosine_similarity,
    episodic_in_window,
    query_time_window,
    retrieval_allowed,
    retrieval_score,
    topic_related,
)
from app.modules.memory.services.memory_service import MemoryService
from app.modules.memory.services.retrieval import MemoryRetrievalService
from app.modules.model_adapter.domain.embedding import EMBEDDING_DIMENSIONS, EmbeddingResult
from app.modules.model_adapter.domain.errors import ModelTimeoutError
from app.shared.database.session import dispose_engine, get_engine, get_session_factory
from tests.test_dialogue_turn import _Adapter, _client, _events, _prepare, _suggestion
from app.modules.dialogue.domain.enums import DialogueAction


def _allowed(**overrides: object) -> bool:
    values: dict[str, object] = {
        "status": "candidate",
        "origin": "user_explicit",
        "is_inference": False,
        "content": "用户喜欢喝茶",
        "valid_from": None,
        "valid_until": None,
        "has_message_evidence": False,
        "query": "我还是喜欢喝茶",
        "subject": None,
        "summary": None,
        "category": "preference",
        "now": datetime(2026, 11, 5, tzinfo=UTC),
        "include_archived": False,
    }
    values.update(overrides)
    return retrieval_allowed(**values)  # type: ignore[arg-type]


def test_candidate_needs_reliable_source_and_topic_before_any_score() -> None:
    assert _allowed() is True
    assert _allowed(query="今天天气不错") is False
    assert _allowed(origin="ai_inference", is_inference=True, has_message_evidence=False) is False
    assert _allowed(origin="ai_inference", is_inference=True, has_message_evidence=True) is True
    assert _allowed(status="rejected") is False
    assert _allowed(status="archived") is False
    assert _allowed(status="archived", include_archived=True) is True
    assert _allowed(status="pending", query="今天天气不错") is True
    assert _allowed(valid_until=datetime(2000, 1, 1, tzinfo=UTC)) is False
    assert _allowed(memory_type="working") is False
    high = retrieval_score(
        related=True,
        confidence=Decimal("1"),
        reliable=True,
        status="rejected",
        importance=100,
    )
    assert high > Decimal("0.500")
    assert _allowed(status="rejected") is False
    assert _allowed(query="今天天气不错", vector_match=True) is True
    assert _allowed(query="今天天气不错", time_match=True) is True
    assert _allowed(query="今天天气不错", relation_match=True) is True
    assert _allowed(query="今天天气不错", vector_match=True, origin="ai_inference", is_inference=True) is False
    assert _allowed(status="rejected", vector_match=True) is False
    now = datetime(2026, 11, 6, 15, tzinfo=UTC)
    yesterday = query_time_window("昨天怎么了", now)
    assert yesterday == (datetime(2026, 11, 5, tzinfo=UTC), datetime(2026, 11, 6, tzinfo=UTC))
    assert query_time_window("我还是喜欢喝茶", now) is None
    assert episodic_in_window("episodic", datetime(2026, 11, 5, 12, tzinfo=UTC), yesterday) is True
    assert episodic_in_window("semantic", datetime(2026, 11, 5, 12, tzinfo=UTC), yesterday) is False
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0
    assert topic_related("我还是喜欢喝茶", "用户偏好热饮", None, None, "preference") is False


@pytest.fixture
async def database_ready():
    await dispose_engine()
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        await dispose_engine()
        pytest.skip(f"PostgreSQL 不可用，跳过集成测试: {exc}")
    try:
        yield
    finally:
        await dispose_engine()


@pytest.mark.asyncio
async def test_turn_uses_eligible_memories_without_promoting_them(database_ready: None) -> None:
    adapter = _Adapter([_suggestion(DialogueAction.QUIET, False)])
    async with _client(adapter) as client:
        scope = await _prepare(client)
        earlier = await client.post(
            scope.messages,
            json={"sender_type": "user", "content": "以前提过喝茶"},
        )
        earlier_id = earlier.json()["id"]
        created = {}
        for key, body in {
            "tea": {"content": "用户喜欢喝茶", "memory_origin": "user_explicit", "is_inference": False},
            "cat": {"content": "用户养了一只猫", "memory_origin": "user_explicit", "is_inference": False},
            "rejected": {"content": "用户喜欢喝茶但是这条被拒绝", "memory_origin": "user_explicit", "is_inference": False},
            "expired": {"content": "用户以前喜欢喝茶", "memory_origin": "user_explicit", "is_inference": False},
            "pending": {"content": "用户每周跑步", "memory_origin": "user_explicit", "is_inference": False},
            "archived": {"content": "用户从前喜欢喝茶", "memory_origin": "user_explicit", "is_inference": False},
            "inference": {
                "content": "用户可能喜欢喝茶",
                "memory_origin": "ai_inference",
                "is_inference": True,
                "sources": [{"source_type": "message", "source_role": "evidence", "message_id": earlier_id}],
            },
        }.items():
            response = await client.post(
                f"/api/users/{scope.user_id}/companions/{scope.companion_id}/memories",
                json={
                    "memory_type": "semantic",
                    "memory_category": "preference",
                    "change_reason": "检索测试",
                    **body,
                },
            )
            assert response.status_code == 201
            created[key] = response.json()["id"]
        async with get_engine().begin() as connection:
            await connection.execute(
                text("UPDATE memories SET status = 'rejected' WHERE id = :memory_id"),
                {"memory_id": created["rejected"]},
            )
            await connection.execute(
                text("UPDATE memories SET status = 'pending' WHERE id = :memory_id"),
                {"memory_id": created["pending"]},
            )
            await connection.execute(
                text("UPDATE memories SET valid_until = TIMESTAMPTZ '2000-01-01 00:00:00+00' WHERE id = :memory_id"),
                {"memory_id": created["expired"]},
            )
            await connection.execute(
                text("UPDATE memories SET status = 'archived', archived_at = NOW() WHERE id = :memory_id"),
                {"memory_id": created["archived"]},
            )
        response = await client.post(scope.turns, json={"content": "我还是喜欢喝茶"})
        _events(response)
        prompt = adapter.calls[0][1][1].content
        assert created["tea"] in prompt
        assert created["inference"] in prompt
        assert created["pending"] in prompt
        assert created["cat"] not in prompt
        assert created["rejected"] not in prompt
        assert created["expired"] not in prompt
        assert created["archived"] not in prompt
        assert '"memory_status": "candidate"' in prompt
        assert '"is_inference": true' in prompt
        assert '"source": "current_message"' in prompt
        assert "我还是喜欢喝茶" in prompt
        assert "retrieval_score" not in prompt
        assert "promotion_score" not in prompt
        # 不把旧的关系总分当作可见好感度；attachment_state.closeness_desire 是内部依恋字段，允许出现。
        parsed_prompt = json.loads(prompt)
        state = parsed_prompt["state"]
        assert "closeness" not in state
        assert "trust" not in state
        assert "attachment" not in state
        assert "attachment_state" in state
        tea = await client.get(f"/api/users/{scope.user_id}/companions/{scope.companion_id}/memories/{created['tea']}")
        assert tea.json()["status"] == "candidate"
        async with get_session_factory()() as session:
            archived = await MemoryRetrievalService().retrieve(
                session,
                uuid.UUID(scope.user_id),
                uuid.UUID(scope.companion_id),
                "我还是喜欢喝茶",
                include_archived=True,
            )
        assert created["archived"] in {item["memory_id"] for item in archived}
        assert all(item["memory_status"] != "rejected" for item in archived)


class _QueryVectors:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def embed(self, task: object, texts: list[str], scope: object) -> EmbeddingResult:
        del task, scope
        self.calls += 1
        if self.error is not None:
            raise self.error
        axis = 0 if "喝茶" in texts[0] else 2
        return EmbeddingResult(model_name="BAAI/bge-m3", vectors=[_axis(axis)])


def _axis(index: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


@pytest.mark.asyncio
async def test_hybrid_retrieval_keeps_keyword_time_and_relation_when_vectors_fail(database_ready: None) -> None:
    vectors = _QueryVectors()
    user_id, companion_id, memories = await _hybrid_memories()
    plain_id = await _create_plain_memory()
    async with get_session_factory()() as session:
        missed = await MemoryRetrievalService(embedder=vectors).retrieve(
            session, uuid.UUID(plain_id[0]), uuid.UUID(plain_id[1]), "我还是喜欢喝茶"
        )
    assert plain_id[2] in {item["memory_id"] for item in missed}
    assert vectors.calls == 0

    found = await _retrieve(vectors, user_id, companion_id, "我还是喜欢喝茶")
    found_ids = {item["memory_id"] for item in found}
    assert memories["tea"] in found_ids
    assert memories["hot"] in found_ids
    assert memories["family"] in found_ids
    assert memories["cat"] not in found_ids
    assert memories["piano"] not in found_ids
    assert memories["hospital"] not in found_ids
    assert vectors.calls == 1

    yesterday = await _retrieve(vectors, user_id, companion_id, "昨天怎么了")
    yesterday_ids = {item["memory_id"] for item in yesterday}
    assert memories["hospital"] in yesterday_ids
    assert memories["tea"] not in yesterday_ids

    failed = _QueryVectors(ModelTimeoutError("模型调用超时"))
    degraded = await _retrieve(failed, user_id, companion_id, "我还是喜欢喝茶")
    degraded_ids = {item["memory_id"] for item in degraded}
    assert memories["tea"] in degraded_ids
    assert memories["family"] in degraded_ids
    assert memories["hot"] not in degraded_ids
    assert failed.calls == 1

    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE memory_embeddings
                SET content_hash = 'stale'
                WHERE memory_version_id = (
                    SELECT current_version_id FROM memories WHERE id = :memory_id
                )
                """
            ),
            {"memory_id": memories["hot"]},
        )
    stale = await _retrieve(vectors, user_id, companion_id, "我还是喜欢喝茶")
    stale_ids = {item["memory_id"] for item in stale}
    assert memories["hot"] not in stale_ids
    assert memories["tea"] in stale_ids


async def _retrieve(embedder: _QueryVectors, user_id: str, companion_id: str, query: str) -> list[dict[str, object]]:
    async with get_session_factory()() as session:
        return await MemoryRetrievalService(embedder=embedder).retrieve(
            session, uuid.UUID(user_id), uuid.UUID(companion_id), query
        )


async def _hybrid_memories() -> tuple[str, str, dict[str, str]]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "混合检索用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "混合检索陪伴"})
        companion_id = companion.json()["id"]
        base = f"/api/users/{user_id}/companions/{companion_id}/memories"
        created = {}
        bodies = {
            "tea": ("semantic", "preference", "用户喜欢喝茶"),
            "hot": ("semantic", "preference", "用户偏好热饮"),
            "family": ("semantic", "person", "用户的哥哥住在杭州"),
            "cat": ("semantic", "preference", "用户养了一只猫"),
            "piano": ("semantic", "skill", "用户在学钢琴"),
            "hospital": ("episodic", "event", "用户去了医院"),
        }
        versions = {}
        for key, (memory_type, category, content) in bodies.items():
            response = await client.post(
                base,
                json={
                    "memory_type": memory_type,
                    "memory_category": category,
                    "memory_origin": "user_explicit",
                    "content": content,
                    "change_reason": "混合检索",
                },
            )
            assert response.status_code == 201
            body = response.json()
            created[key] = body["id"]
            versions[key] = body["current_version_id"]
        relation = await client.post(
            f"{base}/{created['tea']}/relations",
            json={"target_memory_id": created["family"], "relation_type": "related_to", "strength": 0.8},
        )
        assert relation.status_code == 201
        unrelated = await client.post(
            f"{base}/{created['cat']}/relations",
            json={"target_memory_id": created["piano"], "relation_type": "related_to", "strength": 0.4},
        )
        assert unrelated.status_code == 201
    yesterday = datetime.now(UTC) - timedelta(days=1)
    async with get_engine().begin() as connection:
        await connection.execute(
            text("UPDATE memories SET valid_from = :moment WHERE id = :memory_id"),
            {"moment": yesterday, "memory_id": created["hospital"]},
        )
        await connection.execute(
            text("UPDATE memories SET valid_from = :moment WHERE id = :memory_id"),
            {"moment": yesterday, "memory_id": created["tea"]},
        )
    await _store_vector(user_id, companion_id, created["hot"], versions["hot"], "BAAI/bge-m3", _axis(0))
    await _store_vector(user_id, companion_id, created["cat"], versions["cat"], "BAAI/bge-m3", _axis(1))
    await _store_vector(user_id, companion_id, created["piano"], versions["piano"], "other-model", _axis(0))
    return user_id, companion_id, created


async def _create_plain_memory() -> tuple[str, str, str]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "无向量用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "无向量陪伴"})
        companion_id = companion.json()["id"]
        created = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/memories",
            json={
                "memory_type": "semantic",
                "memory_category": "preference",
                "memory_origin": "user_explicit",
                "content": "用户喜欢喝茶",
                "change_reason": "没有向量",
            },
        )
        assert created.status_code == 201
        return user_id, companion_id, created.json()["id"]


async def _store_vector(
    user_id: str,
    companion_id: str,
    memory_id: str,
    version_id: str,
    model_name: str,
    vector: list[float],
) -> None:
    from app.modules.memory.domain.enums import EmbeddingStatus

    async with get_session_factory()() as session:
        await MemoryService().store_embedding(
            session,
            uuid.UUID(user_id),
            uuid.UUID(companion_id),
            uuid.UUID(memory_id),
            uuid.UUID(version_id),
            embedding_model=model_name,
            status=EmbeddingStatus.COMPLETED,
            embedding=vector,
        )
