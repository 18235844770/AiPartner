import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.modules.memory.domain.retrieval import retrieval_allowed, retrieval_score
from app.modules.memory.services.retrieval import MemoryRetrievalService
from app.shared.database.session import dispose_engine, get_engine, get_session_factory
from tests.test_dialogue_turn import _Adapter, _client, _prepare, _suggestion
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
    high = retrieval_score(
        related=True,
        confidence=Decimal("1"),
        reliable=True,
        status="rejected",
        importance=100,
    )
    assert high > Decimal("0.500")
    assert _allowed(status="rejected") is False


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
        assert response.status_code == 201
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
        assert "closeness" not in prompt
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
