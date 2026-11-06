import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.modules.infrastructure.worker import maintain_state_task
from app.modules.state.domain.enums import InteractionMode
from app.modules.state.domain.maintenance import EMOTION_DECAY_WINDOW, SETTLED_CAUSE, plan_maintenance
from app.modules.state.domain.snapshots import EmotionState, InteractionState
from app.modules.state.services.maintenance import StateMaintenanceService
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


def test_temporary_emotion_fades_and_open_quiet_stays() -> None:
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    emotion = EmotionState(
        primary="happy",
        secondary=["期待"],
        intensity=1,
        valence=0.2,
        arousal=0.4,
        cause_summary="刚聊完",
        updated_at=now - EMOTION_DECAY_WINDOW / 2,
    )
    quiet = InteractionState(
        mode=InteractionMode.QUIET,
        proactive_allowed=False,
        waiting_for_user=False,
        consecutive_unanswered_messages=0,
    )
    halfway = plan_maintenance(emotion, quiet, now)
    assert halfway.emotion is not None
    assert halfway.emotion.primary == "happy"
    assert halfway.emotion.intensity == 0.5
    assert halfway.emotion.arousal == 0
    assert halfway.emotion.valence == 0
    assert halfway.emotion.cause_summary == "刚聊完"
    assert halfway.interaction is None
    assert halfway.reason == "临时情绪随时间衰减"

    settled = plan_maintenance(
        emotion.model_copy(update={"updated_at": now - EMOTION_DECAY_WINDOW}),
        quiet,
        now,
    )
    assert settled.emotion is not None
    assert settled.emotion.primary == "calm"
    assert settled.emotion.intensity == 0
    assert settled.emotion.secondary == []
    assert settled.emotion.cause_summary == SETTLED_CAUSE

    resting = EmotionState(
        primary="calm",
        intensity=0,
        valence=0,
        arousal=0,
        cause_summary="状态初始化",
        updated_at=now - EMOTION_DECAY_WINDOW,
    )
    assert plan_maintenance(resting, quiet, now).emotion is None
    recent = emotion.model_copy(update={"updated_at": now - timedelta(seconds=30)})
    assert plan_maintenance(recent, quiet, now).reason is None


def test_expired_quiet_ends_without_granting_or_clearing_permission() -> None:
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    calm = EmotionState(
        primary="calm",
        intensity=0,
        valence=0,
        arousal=0,
        cause_summary="状态初始化",
        updated_at=now,
    )
    expired = InteractionState(
        mode=InteractionMode.QUIET,
        proactive_allowed=True,
        waiting_for_user=True,
        consecutive_unanswered_messages=2,
        quiet_until=now - timedelta(minutes=1),
    )
    plan = plan_maintenance(calm, expired, now)
    assert plan.emotion is None
    assert plan.interaction is not None
    assert plan.interaction.mode == InteractionMode.AVAILABLE
    assert plan.interaction.proactive_allowed is True
    assert plan.interaction.waiting_for_user is True
    assert plan.interaction.consecutive_unanswered_messages == 2
    assert plan.interaction.quiet_until is None
    paused = expired.model_copy(update={"mode": InteractionMode.PAUSED, "proactive_allowed": False})
    paused_plan = plan_maintenance(calm, paused, now)
    assert paused_plan.interaction is not None
    assert paused_plan.interaction.mode == InteractionMode.PAUSED
    assert paused_plan.interaction.proactive_allowed is False
    future = expired.model_copy(update={"quiet_until": now + timedelta(minutes=10)})
    assert plan_maintenance(calm, future, now).interaction is None


async def test_state_handler_rejects_a_bad_payload() -> None:
    task = type("Task", (), {"companion_id": uuid.uuid4(), "payload": {"user_id": "bad"}})()
    with pytest.raises(ValueError):
        await maintain_state_task(None, task)


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


async def _run(task_id: uuid.UUID, now: datetime):
    service = StateMaintenanceService()

    async def handler(session: object, task: object) -> dict[str, object]:
        payload = task.payload
        return await service.maintain(
            session,  # type: ignore[arg-type]
            user_id=uuid.UUID(str(payload["user_id"])),
            companion_id=task.companion_id,
            now=now,
        )

    return await TaskExecutor().execute(task_id, "worker-test", {"state_maintenance": handler})


async def _task(scope: dict[str, str], key_suffix: str, now: datetime) -> uuid.UUID:
    async with get_session_factory()() as session:
        created = await BackgroundTaskService().create(
            session,
            CreateBackgroundTaskRequest(
                user_id=uuid.UUID(scope["user_id"]),
                companion_id=uuid.UUID(scope["companion_id"]),
                task_type=BackgroundTaskType.STATE_MAINTENANCE,
                task_key=f"state-maintenance:{scope['companion_id']}:{key_suffix}",
                queue_name="state",
                payload={"user_id": scope["user_id"]},
                max_retries=2,
                scheduled_at=now - timedelta(seconds=1),
            ),
        )
    return created.task.id


async def _rewind_emotion(companion_id: str, updated_at: datetime) -> None:
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE companion_states
                SET emotion = jsonb_set(emotion, '{updated_at}', to_jsonb(CAST(:updated_at AS text)), false)
                WHERE companion_id = :companion_id
                """
            ),
            {"updated_at": updated_at.isoformat(), "companion_id": companion_id},
        )


@pytest.mark.asyncio
async def test_maintenance_fades_emotion_and_ends_quiet_without_rewriting_relationship(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    moment = datetime.now(UTC)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "状态维护用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "状态维护陪伴"})
        companion_id = companion.json()["id"]
        base = f"/api/users/{user_id}/companions/{companion_id}/state"
        created = await client.post(base, json={})
        assert created.status_code == 201
        changed = await client.post(
            f"{base}/changes",
            json={
                "expected_version": 1,
                "source_type": "system",
                "reason": "测试准备",
                "emotion": {
                    "primary": "happy",
                    "secondary": ["期待"],
                    "intensity": 1,
                    "valence": 0.2,
                    "arousal": 0.4,
                    "cause_summary": "刚聊完",
                },
                "relationship": {
                    "closeness": 0.4,
                    "trust": 0.3,
                    "attachment": 0.2,
                    "care": 0.5,
                    "current_tension": 0.1,
                    "summary": "刚认识",
                },
                "interaction": {
                    "mode": "quiet",
                    "proactive_allowed": True,
                    "waiting_for_user": False,
                    "consecutive_unanswered_messages": 1,
                    "quiet_until": (moment - timedelta(minutes=5)).isoformat(),
                },
                "motivation": {"primary": "share", "secondary": [], "intensity": 0.6, "reason": "想继续说"},
            },
        )
        assert changed.status_code == 200
    scope = {"user_id": user_id, "companion_id": companion_id}
    await _rewind_emotion(companion_id, moment - EMOTION_DECAY_WINDOW / 2)
    finished = await _run(await _task(scope, "fade", moment), moment)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.result == {"changed": True, "version": 3}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        current = await client.get(base)
        body = current.json()
        assert body["emotion"]["primary"] == "happy"
        assert body["emotion"]["intensity"] == 0.5
        assert body["emotion"]["cause_summary"] == "刚聊完"
        assert body["relationship"]["closeness"] == 0.4
        assert body["relationship"]["summary"] == "刚认识"
        assert body["motivation"]["primary"] == "share"
        assert body["interaction"]["mode"] == "available"
        assert body["interaction"]["proactive_allowed"] is True
        assert body["interaction"]["consecutive_unanswered_messages"] == 1
        assert body["interaction"]["quiet_until"] is None
        events = await client.get(f"{base}/events")
        last = events.json()[-1]
        assert last["source_type"] == "background_task"
        assert last["event_type"] == "multiple_changed"
        assert last["reason"] == "临时情绪随时间衰减；安静时段已经结束"
    again = await _run(await _task(scope, "again", moment), moment)
    assert again is not None
    assert again.status == "completed"
    assert again.result == {"changed": False, "reason": "unchanged"}


@pytest.mark.asyncio
async def test_maintenance_skips_a_missing_state(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    moment = datetime.now(UTC)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "无状态用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "无状态陪伴"})
        companion_id = companion.json()["id"]
    finished = await _run(await _task({"user_id": user_id, "companion_id": companion_id}, "missing", moment), moment)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.result == {"changed": False, "reason": "missing"}


@pytest.mark.asyncio
async def test_hourly_schedule_keeps_one_task_for_an_active_companion(database_ready: None) -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    moment = datetime(2026, 11, 6, 7, 5, tzinfo=UTC)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "定时维护用户"})
        user_id = user.json()["id"]
        active = await client.post(f"/api/users/{user_id}/companions", json={"name": "会维护"})
        active_id = active.json()["id"]
        archived = await client.post(f"/api/users/{user_id}/companions", json={"name": "已归档"})
        archived_id = archived.json()["id"]
        bare = await client.post(f"/api/users/{user_id}/companions", json={"name": "没状态"})
        bare_id = bare.json()["id"]
        assert (await client.post(f"/api/users/{user_id}/companions/{active_id}/state", json={})).status_code == 201
        assert (await client.post(f"/api/users/{user_id}/companions/{archived_id}/state", json={})).status_code == 201
        archived_response = await client.patch(
            f"/api/users/{user_id}/companions/{archived_id}",
            json={"status": "archived"},
        )
        assert archived_response.status_code == 200
    service = StateMaintenanceService()
    await service.schedule_due(now=moment, limit=1000)
    await service.schedule_due(now=moment, limit=1000)
    assert await _maintenance_count(active_id) == 1
    assert await _maintenance_count(archived_id) == 0
    assert await _maintenance_count(bare_id) == 0


async def _maintenance_count(companion_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM background_tasks
                WHERE companion_id = :companion_id AND task_type = 'state_maintenance'
                """
            ),
            {"companion_id": companion_id},
        )
    return int(count or 0)
