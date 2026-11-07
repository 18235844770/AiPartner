import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


pytestmark = pytest.mark.asyncio


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


async def test_persona_initializes_once_and_keeps_mbti_across_versions(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "人格测试用户"})
        user_id = user.json()["id"]
        companion = await client.post(
            f"/api/users/{user_id}/companions",
            json={"name": "人格陪伴"},
        )
        companion_id = companion.json()["id"]
        base = f"/api/users/{user_id}/companions/{companion_id}/persona"
        created = await client.post(base, json={"mbti_type": "INTJ"})
        assert created.status_code == 201
        body = created.json()
        assert body["current_version"]["mbti_type"] == "INTJ"
        assert body["current_version"]["version_number"] == 1
        assert body["initial_version_id"] == body["current_version_id"]
        duplicate = await client.post(base, json={"mbti_type": "ENFP"})
        assert duplicate.status_code == 409
        revised = await client.post(
            f"{base}/versions",
            json={"change_reason": "表达可以更直接", "communication_preferences": {"summary": "更直接"}},
        )
        assert revised.status_code == 201
        revised_body = revised.json()
        assert revised_body["initial_version_id"] == body["initial_version_id"]
        assert revised_body["current_version_id"] != body["current_version_id"]
        assert revised_body["current_version"]["version_number"] == 2
        assert revised_body["current_version"]["mbti_type"] == "INTJ"
        foreign = await client.get(f"/api/users/{uuid.uuid4()}/companions/{companion_id}/persona")
        assert foreign.status_code == 404
    await _cleanup(uuid.UUID(user_id))


async def test_current_version_must_belong_to_the_same_profile(database_ready: None) -> None:
    factory = get_session_factory()
    first_user = uuid.uuid4()
    second_user = uuid.uuid4()
    first_companion = uuid.uuid4()
    second_companion = uuid.uuid4()
    async with factory() as session:
        await _insert_companion(session, first_user, first_companion)
        await _insert_companion(session, second_user, second_companion)
        first_profile, first_version = await _insert_persona(session, first_companion)
        _second_profile, second_version = await _insert_persona(session, second_companion)
        await session.commit()
    async with factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text("UPDATE persona_profiles SET current_version_id = :version_id WHERE id = :profile_id"),
                {"version_id": second_version, "profile_id": first_profile},
            )
            await session.commit()
        await session.rollback()
    assert first_version != second_version
    await _cleanup(first_user)
    await _cleanup(second_user)


async def _insert_companion(session, user_id: uuid.UUID, companion_id: uuid.UUID) -> None:
    await session.execute(
        text(
            """
            INSERT INTO users (id, display_name, timezone, locale, status)
            VALUES (:id, :display_name, 'UTC', 'zh-CN', 'active')
            """
        ),
        {"id": user_id, "display_name": f"人格约束 {user_id.hex[:8]}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO companions (id, owner_user_id, name, status, is_default)
            VALUES (:id, :owner_user_id, '约束', 'active', false)
            """
        ),
        {"id": companion_id, "owner_user_id": user_id},
    )


async def _insert_persona(session, companion_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    profile_id = uuid.uuid4()
    version_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO persona_profiles (id, companion_id, initial_version_id, current_version_id)
            VALUES (:id, :companion_id, :version_id, :version_id)
            """
        ),
        {"id": profile_id, "companion_id": companion_id, "version_id": version_id},
    )
    archive = {
        "identity": {
            "identity_summary": "测试身份",
            "core_temperament": ["温和"],
            "cognitive_style": ["观察"],
            "thinking_habits": ["先看依据"],
            "value_orientation": ["边界"],
            "emotional_structure": ["克制"],
            "emotional_expression": ["少而准"],
            "social_tendency": ["先观察"],
            "intimate_relationship": ["慢慢靠近"],
            "communication_tendency": ["直接说"],
            "interest_tendency": ["主题"],
            "natural_behavior": ["分享洞察"],
            "strengths": ["连续判断"],
            "weaknesses": ["想太久"],
            "internal_conflicts": ["靠近与边界"],
            "misconceptions": ["内敛仍可主动"],
            "personality_narrative": "测试叙述",
        },
        "relationship": {
            "attachment_disposition": {
                "attachment_tendency": "high",
                "emotional_dependency_tendency": "medium",
                "exclusivity_tendency": "medium",
                "separation_sensitivity": "high",
                "reassurance_need": "medium",
                "affection_expression": "medium",
                "jealousy_tendency": "medium",
                "possessiveness_tendency": "medium",
                "independence_need": "medium",
            },
            "relationship_preferences": {
                "preferred_closeness": "high",
                "preferred_interaction": ["深层交流"],
                "specialness_need": "high",
                "emotional_boundaries": ["不控制对方"],
            },
            "self_assertion": {
                "assertiveness": "medium",
                "resentment_tendency": "medium",
                "confrontation_tendency": "medium",
                "forgiveness_tendency": "medium",
            },
        },
        "self_model": {
            "entity_type": "artificial_intelligence",
            "human_identity": False,
            "self_awareness": "知道自己是 AI",
            "physical_existence": "没有人类身体",
            "biological_needs": "无人类生理需求",
            "experience_boundary": "不编造经历",
            "emotional_capability": "允许情感",
            "relationship_capability": "允许依恋",
            "identity_consistency": "身份稳定",
            "disclosure_policy": "被问再澄清",
        },
        "background": "测试背景",
        "interests": ["主题"],
        "viewpoints": ["观点"],
        "attention": ["未完成的判断"],
    }
    await session.execute(
        text(
            """
            INSERT INTO persona_versions (
                id, persona_profile_id, version_number, mbti_type,
                core_traits, behavior_traits, communication_preferences, archive, change_reason
            )
            VALUES (
                :id, :persona_profile_id, 1, 'INFJ',
                '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                CAST(:archive AS jsonb),
                '初始人格'
            )
            """
        ),
        {
            "id": version_id,
            "persona_profile_id": profile_id,
            "archive": json.dumps(archive, ensure_ascii=False),
        },
    )
    return profile_id, version_id


async def _cleanup(user_id: uuid.UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                DELETE FROM persona_versions
                WHERE persona_profile_id IN (
                    SELECT id FROM persona_profiles
                    WHERE companion_id IN (SELECT id FROM companions WHERE owner_user_id = :user_id)
                )
                """
            ),
            {"user_id": user_id},
        )
        await session.execute(
            text(
                """
                DELETE FROM persona_profiles
                WHERE companion_id IN (SELECT id FROM companions WHERE owner_user_id = :user_id)
                """
            ),
            {"user_id": user_id},
        )
        await session.execute(
            text(
                """
                DELETE FROM messages
                WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = :user_id)
                """
            ),
            {"user_id": user_id},
        )
        await session.execute(text("DELETE FROM conversations WHERE user_id = :user_id"), {"user_id": user_id})
        await session.execute(text("DELETE FROM companions WHERE owner_user_id = :user_id"), {"user_id": user_id})
        await session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})
        await session.commit()
