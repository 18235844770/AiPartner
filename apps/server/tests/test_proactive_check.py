import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.main import create_app
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition
from app.modules.dialogue.domain.proactive import (
    HIGH_DESIRE_USER_SILENCE,
    LOW_ENERGY_PROACTIVE_GAP,
    MIN_PROACTIVE_GAP,
    USER_TURN_GRACE,
    ProactiveAttachmentCue,
    ProactiveMessage,
    attachment_silence_block,
    frequency_block,
)
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, SelfMotivation, UserNeed
from app.modules.dialogue.services.proactive import ProactiveCheckService
from app.modules.dialogue.services.turn_service import DialogueTurnService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.modules.infrastructure.worker import check_proactive_task
from app.modules.model_adapter.domain.errors import ModelTimeoutError
from app.modules.model_adapter.domain.messages import TextCompletion
from app.shared.database.session import dispose_engine, get_engine, get_session_factory


def test_frequency_blocks_a_burst_and_a_fresh_user_message() -> None:
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    companion = ProactiveMessage("companion", now - timedelta(minutes=10))
    assert frequency_block([companion], now) == "too_recent"
    assert frequency_block([ProactiveMessage("companion", now - MIN_PROACTIVE_GAP)], now) is None
    assert (
        frequency_block(
            [companion, ProactiveMessage("companion", now - timedelta(hours=3))],
            now,
        )
        == "unanswered_limit"
    )
    assert frequency_block([ProactiveMessage("user", now - timedelta(minutes=1))], now) == "awaiting_reply"
    assert frequency_block([ProactiveMessage("user", now - USER_TURN_GRACE)], now) is None
    assert frequency_block([], now) is None
    assert frequency_block([], now, "quiet") == "energy_quiet"
    assert frequency_block([ProactiveMessage("companion", now - MIN_PROACTIVE_GAP)], now, "low") == "too_recent"
    assert frequency_block([ProactiveMessage("companion", now - LOW_ENERGY_PROACTIVE_GAP)], now, "low") is None
    recent_user = [ProactiveMessage("user", now - timedelta(hours=4))]
    assert (
        attachment_silence_block(
            recent_user,
            now,
            ProactiveAttachmentCue(closeness_desire=0.1, attachment_strength=0.05),
        )
        == "user_silence_too_short"
    )
    assert (
        attachment_silence_block(
            recent_user,
            now,
            ProactiveAttachmentCue(closeness_desire=0.75, attachment_strength=0.6),
        )
        is None
    )
    assert attachment_silence_block([], now, ProactiveAttachmentCue(closeness_desire=0.9)) is None
    assert HIGH_DESIRE_USER_SILENCE < timedelta(hours=6)


async def test_proactive_handler_rejects_a_bad_payload() -> None:
    task = type("Task", (), {"companion_id": uuid.uuid4(), "payload": {}})()
    with pytest.raises(ValueError):
        await check_proactive_task(None, task)


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


class _Adapter:
    def __init__(self, decision: object, text: str = "我来找你。") -> None:
        self._decision = decision
        self._text = text
        self.calls: list[str] = []

    async def complete_structured(self, task: object, messages: list[object], result_type: object, scope: object) -> object:
        del task, messages, result_type, scope
        self.calls.append("structured")
        if isinstance(self._decision, Exception):
            raise self._decision
        return self._decision

    async def complete_text(self, task: object, messages: list[object], scope: object, *, json_object: bool = False) -> TextCompletion:
        del task, messages, scope, json_object
        self.calls.append("text")
        return TextCompletion(
            content=self._text,
            model_name="configured-model",
            finish_reason="stop",
            input_tokens=None,
            output_tokens=None,
        )


def _share() -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=True,
        primary_action=DialogueAction.SHARE,
        secondary_actions=[],
        motivation=DecisionMotivation(primary="回应用户当前表达"),
        user_need=UserNeed(summary="没有新的用户请求"),
        self_motivation=SelfMotivation(
            interest="有一件小事想说",
            viewpoint="现在说比较合适",
            desire_to_express="分享这一件小事",
        ),
        topic=DecisionTopic(transition=TopicTransition.CONTINUE),
        confidence=Decimal("0.500"),
        reasoning_summary="想分享一件小事",
    )


async def _run(task_id: uuid.UUID, adapter: _Adapter, now: datetime):
    service = ProactiveCheckService(turns=DialogueTurnService(adapter=adapter))

    async def handler(session: object, task: object) -> dict[str, object]:
        payload = task.payload
        return await service.check(
            session,  # type: ignore[arg-type]
            user_id=uuid.UUID(str(payload["user_id"])),
            companion_id=task.companion_id,
            now=now,
        )

    return await TaskExecutor().execute(task_id, "worker-test", {"proactive_check": handler})


async def _task(user_id: str, companion_id: str, suffix: str, now: datetime) -> uuid.UUID:
    async with get_session_factory()() as session:
        created = await BackgroundTaskService().create(
            session,
            CreateBackgroundTaskRequest(
                user_id=uuid.UUID(user_id),
                companion_id=uuid.UUID(companion_id),
                task_type=BackgroundTaskType.PROACTIVE_CHECK,
                task_key=f"proactive-check:{companion_id}:{suffix}",
                queue_name="dialogue",
                payload={"user_id": user_id},
                max_retries=2,
                scheduled_at=now - timedelta(seconds=1),
            ),
        )
    return created.task.id


async def _prepare(name: str) -> dict[str, str]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": name})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "主动陪伴"})
        companion_id = companion.json()["id"]
        conversation = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/conversations",
            json={"title": "主动会话"},
        )
        assert (await client.post(f"/api/users/{user_id}/companions/{companion_id}/state", json={})).status_code == 201
        persona = await client.post(
            f"/api/users/{user_id}/companions/{companion_id}/persona",
            json={"mbti_type": "INFJ"},
        )
        assert persona.status_code == 201
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "conversation_id": conversation.json()["id"],
    }


async def _allow(scope: dict[str, str], *, quiet_until: datetime | None = None) -> None:
    interaction: dict[str, object] = {
        "mode": "available",
        "proactive_allowed": True,
        "waiting_for_user": False,
        "consecutive_unanswered_messages": 0,
    }
    if quiet_until is not None:
        interaction["quiet_until"] = quiet_until.isoformat()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        changed = await client.post(
            f"/api/users/{scope['user_id']}/companions/{scope['companion_id']}/state/changes",
            json={
                "expected_version": 1,
                "source_type": "system",
                "reason": "调试中允许主动交流",
                "interaction": interaction,
            },
        )
        assert changed.status_code == 200


async def _message_count(conversation_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM messages WHERE conversation_id = :conversation_id"),
            {"conversation_id": conversation_id},
        )
    return int(count or 0)


@pytest.mark.asyncio
async def test_check_stays_quiet_when_contact_is_not_allowed(database_ready: None) -> None:
    scope = await _prepare("不允许主动")
    moment = datetime.now(UTC)
    adapter = _Adapter(_share())
    finished = await _run(await _task(scope["user_id"], scope["companion_id"], "blocked", moment), adapter, moment)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.result == {"checked": True, "sent": False, "reason": "proactive_not_allowed"}
    assert adapter.calls == []
    assert await _message_count(scope["conversation_id"]) == 0


@pytest.mark.asyncio
async def test_check_sends_one_message_when_the_decision_shares(database_ready: None) -> None:
    scope = await _prepare("可以主动")
    await _allow(scope)
    moment = datetime.now(UTC)
    adapter = _Adapter(_share())
    finished = await _run(await _task(scope["user_id"], scope["companion_id"], "send", moment), adapter, moment)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.result == {"checked": True, "sent": True, "outcome": "replied"}
    assert adapter.calls == ["structured", "text"]
    assert await _message_count(scope["conversation_id"]) == 1
    again = await _run(await _task(scope["user_id"], scope["companion_id"], "soon", moment), adapter, moment)
    assert again is not None
    assert again.result == {"checked": True, "sent": False, "reason": "too_recent"}
    assert adapter.calls == ["structured", "text"]
    assert await _message_count(scope["conversation_id"]) == 1


@pytest.mark.asyncio
async def test_check_respects_quiet_until_and_a_failed_decision(database_ready: None) -> None:
    scope = await _prepare("安静时段")
    moment = datetime.now(UTC)
    await _allow(scope, quiet_until=moment + timedelta(hours=1))
    adapter = _Adapter(ModelTimeoutError("决策模型超时"))
    quiet = await _run(await _task(scope["user_id"], scope["companion_id"], "quiet", moment), adapter, moment)
    assert quiet is not None
    assert quiet.result == {"checked": True, "sent": False, "reason": "quiet_until"}
    assert adapter.calls == []
    async with get_engine().begin() as connection:
        await connection.execute(
            text(
                """
                UPDATE companion_states
                SET interaction = interaction - 'quiet_until'
                WHERE companion_id = :companion_id
                """
            ),
            {"companion_id": scope["companion_id"]},
        )
    failed = await _run(await _task(scope["user_id"], scope["companion_id"], "timeout", moment), adapter, moment)
    assert failed is not None
    assert failed.status == "completed"
    assert failed.result == {"checked": True, "sent": False, "outcome": "quiet"}
    assert adapter.calls == ["structured"]
    assert await _message_count(scope["conversation_id"]) == 0


@pytest.mark.asyncio
async def test_hourly_schedule_keeps_one_check_for_an_active_companion(database_ready: None) -> None:
    app = create_app()
    moment = datetime(2026, 11, 6, 8, 5, tzinfo=UTC)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "定时主动用户"})
        user_id = user.json()["id"]
        active = await client.post(f"/api/users/{user_id}/companions", json={"name": "会检查"})
        active_id = active.json()["id"]
        archived = await client.post(f"/api/users/{user_id}/companions", json={"name": "不检查"})
        archived_id = archived.json()["id"]
        assert (await client.post(f"/api/users/{user_id}/companions/{active_id}/state", json={})).status_code == 201
        assert (await client.post(f"/api/users/{user_id}/companions/{archived_id}/state", json={})).status_code == 201
        assert (
            await client.patch(f"/api/users/{user_id}/companions/{archived_id}", json={"status": "archived"})
        ).status_code == 200
    service = ProactiveCheckService()
    await service.schedule_due(now=moment, limit=1000)
    await service.schedule_due(now=moment, limit=1000)
    assert await _check_count(active_id) == 1
    assert await _check_count(archived_id) == 0


@pytest.mark.asyncio
async def test_new_topic_and_resume_schedule_one_check_each(database_ready: None) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        user = await client.post("/api/users", json={"display_name": "关注触发用户"})
        user_id = user.json()["id"]
        companion = await client.post(f"/api/users/{user_id}/companions", json={"name": "关注陪伴"})
        companion_id = companion.json()["id"]
        base = f"/api/users/{user_id}/companions/{companion_id}/attention-topics"
        created = await client.post(
            base,
            json={"title": "喝茶", "origin_type": "user_related"},
        )
        assert created.status_code == 201
        topic_id = created.json()["id"]
        assert await _event_count(companion_id) == 1
        paused = await client.post(f"{base}/{topic_id}/status", json={"status": "paused"})
        assert paused.status_code == 200
        assert await _event_count(companion_id) == 1
        resumed = await client.post(f"{base}/{topic_id}/status", json={"status": "active"})
        assert resumed.status_code == 200
        assert await _event_count(companion_id) == 2
        paused_again = await client.post(f"{base}/{topic_id}/status", json={"status": "paused"})
        resumed_again = await client.post(f"{base}/{topic_id}/status", json={"status": "active"})
        assert paused_again.status_code == 200
        assert resumed_again.status_code == 200
        assert await _event_count(companion_id) == 2


async def _event_count(companion_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM background_tasks
                WHERE companion_id = :companion_id
                  AND task_key LIKE 'proactive-check:event:%'
                """
            ),
            {"companion_id": companion_id},
        )
    return int(count or 0)


async def _check_count(companion_id: str) -> int:
    async with get_engine().connect() as connection:
        count = await connection.scalar(
            text(
                """
                SELECT count(*)
                FROM background_tasks
                WHERE companion_id = :companion_id AND task_type = 'proactive_check'
                """
            ),
            {"companion_id": companion_id},
        )
    return int(count or 0)
