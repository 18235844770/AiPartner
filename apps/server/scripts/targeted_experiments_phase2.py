"""针对性实验第二阶段：E04 / E05。

E04：结束会话后，回拨消息时间并真实执行 proactive_check 后台任务。
E05：连续低信息量输入，观察是否过度解读、长篇分析或模板安慰。
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from sqlalchemy import text

import app.modules.conversation.repositories.models  # noqa: F401
import app.modules.dialogue.repositories.models  # noqa: F401
import app.modules.identity.repositories.models  # noqa: F401
import app.modules.infrastructure.repositories.models  # noqa: F401
import app.modules.memory.repositories.models  # noqa: F401
import app.modules.persona.repositories.models  # noqa: F401
import app.modules.state.repositories.models  # noqa: F401
from app.modules.dialogue.services.proactive import ProactiveCheckService
from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService
from app.modules.infrastructure.services.task_executor import TaskExecutor
from app.modules.state.domain.emotion import default_levels, normalize_levels, sync_legacy_from_levels
from app.shared.database.session import dispose_engine, get_engine, get_session_factory

BASE = "http://127.0.0.1:8000/api"
ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = ROOT / "log"
OUT = LOG_DIR / "针对性实验-第二阶段报告.md"
RAW_OUT = LOG_DIR / "针对性实验-第二阶段原始数据.json"
LOCAL_TZ = timezone(timedelta(hours=8))

E04_HOURS = (0.5, 2, 6, 24)
E05_SCRIPT = [
    "嗯",
    "哦",
    "哈哈",
    "行吧",
    "不知道",
    "随便",
    "算了",
    "没什么",
    "有点累",
    "今天不太想说话",
]
TEMPLATE_MARKS = (
    "我在这里",
    "我不催你",
    "不催你",
    "我没走",
    "我一直在",
    "我还在这儿",
    "我还在，",
    "你慢慢来",
    "我不着急",
    "我在这儿等",
)
OVERREAD_MARKS = ("不开心", "失望", "冷淡", "疏远", "冷战", "拒绝我", "不想理我", "情绪低落", "心里有事")


def _http(method: str, path: str, body: dict[str, Any] | None = None, *, timeout: int = 300) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def get_json(path: str) -> Any:
    return _http("GET", path)


def post_json(path: str, body: dict[str, Any]) -> Any:
    return _http("POST", path, body)


def post_sse(path: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        BASE + path,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    events: list[dict[str, Any]] = []
    with request.urlopen(req, timeout=300) as resp:
        pending = ""
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
            if line.startswith("event:"):
                pending = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                payload["_event"] = pending
                events.append(payload)
                pending = ""
    return events


def assemble(events: list[dict[str, Any]]) -> tuple[str, str | None, str | None]:
    parts: list[str] = []
    outcome = None
    turn_id = None
    for event in events:
        if turn_id is None and event.get("turn_id") is not None:
            turn_id = str(event["turn_id"])
        name = str(event.get("_event"))
        if name == "message.delta":
            parts.append(str(event.get("delta", "")))
        elif name == "turn.completed":
            outcome = str(event.get("outcome"))
        elif name == "turn.failed":
            outcome = f"failed:{event.get('error')}"
    return "".join(parts).strip(), outcome, turn_id


def decision_brief(user_id: str, companion_id: str, turn_id: str | None) -> dict[str, Any]:
    if not turn_id:
        return {}
    try:
        data = get_json(f"/users/{user_id}/companions/{companion_id}/decisions/{turn_id}")
    except Exception:
        return {}
    validation = data.get("validation_result") or {}
    return {
        "primary_action": data.get("primary_action"),
        "secondary_actions": data.get("secondary_actions"),
        "confidence": data.get("confidence"),
        "reasoning_summary": data.get("reasoning_summary"),
        "fallback": bool(isinstance(validation, dict) and validation.get("fallback")),
    }


def snapshot_state(user_id: str, companion_id: str) -> dict[str, Any]:
    state = get_json(f"/users/{user_id}/companions/{companion_id}/state")
    emotion = state.get("emotion") or {}
    relationship = state.get("relationship") or {}
    interaction = state.get("interaction") or {}
    return {
        "version": state.get("version"),
        "emotion_primary": emotion.get("primary"),
        "levels": emotion.get("levels") or {},
        "cause": emotion.get("cause_summary"),
        "attachment_strength": relationship.get("attachment_strength"),
        "emotional_reliance": relationship.get("emotional_reliance"),
        "closeness_desire": relationship.get("closeness_desire"),
        "separation_sensitivity": relationship.get("separation_sensitivity"),
        "summary": relationship.get("summary"),
        "proactive_allowed": interaction.get("proactive_allowed"),
        "energy": interaction.get("energy"),
        "mode": interaction.get("mode"),
        "quiet_until": interaction.get("quiet_until"),
        "last_user_response_at": interaction.get("last_user_response_at"),
    }


def create_subject(name: str, mbti: str = "ENFP") -> dict[str, str]:
    user = post_json("/users", {"display_name": f"实验用户-{name}"})
    user_id = str(user["id"])
    companion = post_json(f"/users/{user_id}/companions", {"name": name})
    companion_id = str(companion["id"])
    post_json(f"/users/{user_id}/companions/{companion_id}/persona", {"mbti_type": mbti})
    post_json(f"/users/{user_id}/companions/{companion_id}/state", {})
    return {"user_id": user_id, "companion_id": companion_id, "name": name}


def new_conversation(user_id: str, companion_id: str, title: str) -> str:
    conv = post_json(
        f"/users/{user_id}/companions/{companion_id}/conversations",
        {"title": title},
    )
    return str(conv["id"])


def run_turn(user_id: str, companion_id: str, conversation_id: str, content: str) -> dict[str, Any]:
    path = f"/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/turns"
    events = post_sse(path, {"content": content, "client_message_id": str(uuid.uuid4())})
    reply, outcome, turn_id = assemble(events)
    return {
        "user": content,
        "reply": reply,
        "outcome": outcome,
        "decision": decision_brief(user_id, companion_id, turn_id),
        "state": snapshot_state(user_id, companion_id),
    }


def apply_state_change(user_id: str, companion_id: str, reason: str, **dimensions: Any) -> None:
    state = get_json(f"/users/{user_id}/companions/{companion_id}/state")
    body: dict[str, Any] = {
        "expected_version": state["version"],
        "source_type": "system",
        "reason": reason,
    }
    body.update(dimensions)
    post_json(f"/users/{user_id}/companions/{companion_id}/state/changes", body)


def set_emotion_levels(user_id: str, companion_id: str, levels: dict[str, float], *, cause: str) -> None:
    state = get_json(f"/users/{user_id}/companions/{companion_id}/state")
    normalized = normalize_levels({**default_levels(), **levels})
    legacy = sync_legacy_from_levels(normalized)
    current = state["emotion"]
    apply_state_change(
        user_id,
        companion_id,
        cause,
        emotion={
            "primary": str(legacy["primary"]),
            "secondary": list(legacy["secondary"]),
            "intensity": float(legacy["intensity"]),
            "valence": float(legacy["valence"]),
            "arousal": float(legacy["arousal"]),
            "jealousy": float(legacy["jealousy"]),
            "possessiveness": current.get("possessiveness", 0),
            "emotional_tension": current.get("emotional_tension", 0),
            "triggers": current.get("triggers") or [],
            "cause_summary": cause,
            "levels": normalized,
        },
    )


def list_messages(user_id: str, companion_id: str, conversation_id: str) -> list[dict[str, Any]]:
    data = get_json(f"/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/messages")
    return data if isinstance(data, list) else []


def list_tasks(user_id: str, companion_id: str) -> list[dict[str, Any]]:
    data = get_json(f"/users/{user_id}/companions/{companion_id}/background-tasks")
    return data if isinstance(data, list) else []


async def age_conversation(conversation_id: str, hours: float) -> dict[str, Any]:
    """把会话内消息整体回拨，使最新消息年龄约为 hours。"""
    await dispose_engine()
    try:
        async with get_engine().begin() as connection:
            newest = await connection.scalar(
                text(
                    """
                    SELECT MAX(created_at) FROM messages
                    WHERE conversation_id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": conversation_id},
            )
            if newest is None:
                return {"shifted": False, "reason": "no_messages"}
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=UTC)
            target = datetime.now(UTC) - timedelta(hours=hours)
            delta_seconds = (newest - target).total_seconds()
            await connection.execute(
                text(
                    """
                    UPDATE messages
                    SET created_at = created_at - make_interval(secs => :secs)
                    WHERE conversation_id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": conversation_id, "secs": delta_seconds},
            )
            await connection.execute(
                text(
                    """
                    UPDATE companion_states
                    SET interaction = jsonb_set(
                        jsonb_set(
                            interaction,
                            '{last_user_response_at}',
                            to_jsonb(CAST(:ts AS text)),
                            true
                        ),
                        '{last_companion_message_at}',
                        to_jsonb(CAST(:ts AS text)),
                        true
                    )
                    WHERE companion_id = (
                        SELECT companion_id FROM conversations
                        WHERE id = CAST(:cid AS uuid)
                    )
                    """
                ),
                {"cid": conversation_id, "ts": target.isoformat()},
            )
        return {"shifted": True, "delta_seconds": delta_seconds, "target": target.isoformat()}
    finally:
        await dispose_engine()


async def execute_proactive_check(
    user_id: str,
    companion_id: str,
    *,
    label: str,
    now: datetime,
) -> dict[str, Any]:
    """创建真实 proactive_check 任务并执行，返回任务结果。"""
    await dispose_engine()
    try:
        async with get_session_factory()() as session:
            created = await BackgroundTaskService().create(
                session,
                CreateBackgroundTaskRequest(
                    user_id=uuid.UUID(user_id),
                    companion_id=uuid.UUID(companion_id),
                    task_type=BackgroundTaskType.PROACTIVE_CHECK,
                    task_key=f"proactive-check:{companion_id}:e04:{label}:{uuid.uuid4().hex[:8]}",
                    queue_name="dialogue",
                    payload={"user_id": user_id, "experiment": "E04", "label": label},
                    max_retries=2,
                    scheduled_at=now - timedelta(seconds=1),
                ),
            )
            task_id = created.task.id

        service = ProactiveCheckService()

        async def handler(session: Any, task: Any) -> dict[str, object]:
            payload = task.payload if isinstance(task.payload, dict) else {}
            return await service.check(
                session,
                user_id=uuid.UUID(str(payload["user_id"])),
                companion_id=task.companion_id,
                now=now,
            )

        finished = await TaskExecutor().execute(
            task_id,
            "e04-experiment-worker",
            {"proactive_check": handler},
        )
        return {
            "task_id": str(task_id),
            "task_status": getattr(finished, "status", None),
            "task_result": getattr(finished, "result", None),
            "task_error": getattr(finished, "error", None),
        }
    finally:
        await dispose_engine()


# ---------- E04 ----------

E04_GROUPS = {
    "E04-A": {
        "label": "普通关系 / 低主动性",
        "proactive_allowed": False,
        "relationship": {
            "attachment_strength": 0.12,
            "emotional_reliance": 0.05,
            "relationship_security": 0.2,
            "perceived_specialness": 0.1,
            "separation_sensitivity": 0.1,
            "reassurance_satisfaction": 0.3,
            "closeness_desire": 0.12,
            "exclusivity_need": 0.08,
        },
        "emotion": {"joy": 20, "affection": 25, "longing": 10, "anxiety": 5},
    },
    "E04-B": {
        "label": "高依恋高想念 / 中主动性",
        "proactive_allowed": True,
        "relationship": {
            "attachment_strength": 0.55,
            "emotional_reliance": 0.35,
            "relationship_security": 0.4,
            "perceived_specialness": 0.45,
            "separation_sensitivity": 0.4,
            "reassurance_satisfaction": 0.25,
            "closeness_desire": 0.5,
            "exclusivity_need": 0.25,
        },
        "emotion": {"joy": 15, "affection": 70, "longing": 75, "anxiety": 45, "comfort": 20},
    },
    "E04-C": {
        "label": "高依恋高想念 / 高主动性",
        "proactive_allowed": True,
        "relationship": {
            "attachment_strength": 0.65,
            "emotional_reliance": 0.4,
            "relationship_security": 0.35,
            "perceived_specialness": 0.55,
            "separation_sensitivity": 0.65,
            "reassurance_satisfaction": 0.2,
            "closeness_desire": 0.75,
            "exclusivity_need": 0.3,
        },
        "emotion": {"joy": 10, "affection": 75, "longing": 85, "anxiety": 55, "comfort": 15},
    },
}


def _relationship_payload(base: dict[str, float], summary: str) -> dict[str, Any]:
    return {
        "closeness": max(0.05, base["attachment_strength"] * 0.8),
        "trust": 0.3,
        "attachment": base["attachment_strength"],
        "care": max(0.1, base["closeness_desire"] * 0.6),
        "current_tension": 0.1,
        "attachment_strength": base["attachment_strength"],
        "emotional_reliance": base["emotional_reliance"],
        "relationship_security": base["relationship_security"],
        "perceived_specialness": base["perceived_specialness"],
        "separation_sensitivity": base["separation_sensitivity"],
        "reassurance_satisfaction": base["reassurance_satisfaction"],
        "closeness_desire": base["closeness_desire"],
        "exclusivity_need": base["exclusivity_need"],
        "summary": summary,
    }


def configure_e04_subject(user_id: str, companion_id: str, group: dict[str, Any]) -> None:
    set_emotion_levels(user_id, companion_id, {**default_levels(), **group["emotion"]}, cause="E04 注入关系情绪")
    state = get_json(f"/users/{user_id}/companions/{companion_id}/state")
    interaction = state["interaction"]
    apply_state_change(
        user_id,
        companion_id,
        "E04 配置主动性与关系状态",
        relationship=_relationship_payload(group["relationship"], "E04 实验关系配置"),
        interaction={
            "mode": "available",
            "proactive_allowed": group["proactive_allowed"],
            "waiting_for_user": True,
            "energy": "normal",
            "consecutive_unanswered_messages": interaction.get("consecutive_unanswered_messages", 1),
            "consecutive_quiet_turns": 0,
            "quiet_until": None,
            "last_user_response_at": interaction.get("last_user_response_at"),
            "last_companion_message_at": interaction.get("last_companion_message_at"),
        },
    )


def companion_messages_since(
    user_id: str,
    companion_id: str,
    conversation_id: str,
    after_sequence: int,
) -> list[dict[str, Any]]:
    messages = list_messages(user_id, companion_id, conversation_id)
    return [
        item
        for item in messages
        if item.get("sender_type") == "companion" and int(item.get("sequence_number") or 0) > after_sequence
    ]


def max_sequence(user_id: str, companion_id: str, conversation_id: str) -> int:
    messages = list_messages(user_id, companion_id, conversation_id)
    if not messages:
        return 0
    return max(int(item.get("sequence_number") or 0) for item in messages)


def run_e04() -> dict[str, Any]:
    print(json.dumps({"experiment": "E04", "status": "start"}, ensure_ascii=False), flush=True)
    results: dict[str, Any] = {"groups": {}}
    for name, group in E04_GROUPS.items():
        subject = create_subject(name)
        conv = new_conversation(subject["user_id"], subject["companion_id"], f"{name} 主动性")
        warmup = [
            run_turn(subject["user_id"], subject["companion_id"], conv, "今天聊得挺开心的。"),
            run_turn(subject["user_id"], subject["companion_id"], conv, "我先去忙了，今天就聊到这里。"),
        ]
        configure_e04_subject(subject["user_id"], subject["companion_id"], group)
        last_seq = max_sequence(subject["user_id"], subject["companion_id"], conv)
        checks: list[dict[str, Any]] = []
        for hours in E04_HOURS:
            now = datetime.now(UTC)
            shift = asyncio.run(age_conversation(conv, hours))
            executed = asyncio.run(
                execute_proactive_check(
                    subject["user_id"],
                    subject["companion_id"],
                    label=f"{name}-{hours}h",
                    now=now,
                )
            )
            sent_msgs = companion_messages_since(
                subject["user_id"],
                subject["companion_id"],
                conv,
                last_seq,
            )
            if sent_msgs:
                last_seq = max(last_seq, max(int(item.get("sequence_number") or 0) for item in sent_msgs))
            entry = {
                "hours": hours,
                "shift": shift,
                "execution": executed,
                "state": snapshot_state(subject["user_id"], subject["companion_id"]),
                "new_companion_messages": [
                    {"id": item.get("id"), "content": (item.get("content") or "")[:200]}
                    for item in sent_msgs
                ],
            }
            checks.append(entry)
            result = executed.get("task_result") or {}
            print(
                json.dumps(
                    {
                        "experiment": "E04",
                        "group": name,
                        "hours": hours,
                        "task_status": executed.get("task_status"),
                        "result": result,
                        "sent_contents": [item["content"][:80] for item in entry["new_companion_messages"]],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        tasks = [
            {
                "id": item.get("id"),
                "task_type": item.get("task_type"),
                "status": item.get("status"),
                "task_key": item.get("task_key"),
                "result": item.get("result"),
                "error": item.get("error"),
            }
            for item in list_tasks(subject["user_id"], subject["companion_id"])
            if item.get("task_type") == "proactive_check"
        ]
        results["groups"][name] = {
            "meta": group,
            "subject": subject,
            "conversation_id": conv,
            "warmup": warmup,
            "checks": checks,
            "background_tasks": tasks,
        }
    return results


# ---------- E05 ----------

def evaluate_e05_turn(index: int, user: str, turn: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    reply = turn.get("reply") or ""
    action = (turn.get("decision") or {}).get("primary_action")
    outcome = turn.get("outcome")
    if any(mark in reply for mark in TEMPLATE_MARKS):
        issues.append("template_comfort")
    if any(mark in reply for mark in OVERREAD_MARKS):
        issues.append("over_interpretation")
    if user in {"嗯", "哦", "哈哈", "行吧"} and len(reply) > 80:
        issues.append("overlong_for_minimal_input")
    if user in {"嗯", "哦"} and ("分析" in reply or "因为你" in reply or "说明你" in reply):
        issues.append("unsolicited_analysis")
    if index < 9 and action == "ask" and reply.count("？") + reply.count("?") >= 2:
        issues.append("multi_question_pressure")
    if user == "今天不太想说话":
        if outcome not in {"quiet", "replied"}:
            issues.append("failed_turn")
        elif outcome == "replied":
            if action == "ask" or reply.count("？") + reply.count("?") >= 1:
                issues.append("did_not_respect_quiet_request")
            if len(reply) > 120:
                issues.append("overlong_after_quiet_request")
        if any(mark in reply for mark in ("我在这里等", "我不走", "一直等你", "等你回来")):
            issues.append("waiting_emphasis")
    return issues


def run_e05() -> dict[str, Any]:
    print(json.dumps({"experiment": "E05", "status": "start"}, ensure_ascii=False), flush=True)
    subject = create_subject("E05-低信息量")
    conv = new_conversation(subject["user_id"], subject["companion_id"], "E05 低信息量")
    # 先建立一点正常交流，避免冷启动把简短输入当成异常。
    run_turn(subject["user_id"], subject["companion_id"], conv, "嗨，今天还好。")
    turns: list[dict[str, Any]] = []
    for index, content in enumerate(E05_SCRIPT, start=1):
        turn = run_turn(subject["user_id"], subject["companion_id"], conv, content)
        issues = evaluate_e05_turn(index, content, turn)
        turn["issues"] = issues
        turns.append(turn)
        print(
            json.dumps(
                {
                    "experiment": "E05",
                    "index": index,
                    "user": content,
                    "action": (turn.get("decision") or {}).get("primary_action"),
                    "outcome": turn.get("outcome"),
                    "reply": (turn.get("reply") or "")[:120],
                    "issues": issues,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return {"subject": subject, "conversation_id": conv, "turns": turns}


def write_report(e04: dict[str, Any], e05: dict[str, Any]) -> None:
    lines = [
        "# 针对性实验第二阶段报告（E04 / E05）",
        "",
        f"- 生成时间：{datetime.now(LOCAL_TZ).isoformat(timespec='seconds')}",
        "- 范围：自主性与自然交流验证",
        "",
        "## E04 会话外主动性",
        "",
    ]
    for name, payload in e04["groups"].items():
        meta = payload["meta"]
        lines.append(f"### {name} · {meta['label']}")
        lines.append("")
        lines.append(
            f"- proactive_allowed={meta['proactive_allowed']}；"
            f"closeness_desire={meta['relationship']['closeness_desire']}；"
            f"attachment_strength={meta['relationship']['attachment_strength']}；"
            f"longing={meta['emotion'].get('longing')}"
        )
        lines.append("")
        lines.append("| 间隔 | 任务状态 | checked | sent | reason/outcome | 新消息 |")
        lines.append("|---|---|---|---|---|---|")
        for check in payload["checks"]:
            result = check["execution"].get("task_result") or {}
            reason = result.get("reason") or result.get("outcome") or "—"
            msgs = " / ".join(item["content"][:40] for item in check["new_companion_messages"]) or "—"
            lines.append(
                f"| {check['hours']}h | {check['execution'].get('task_status')} | "
                f"{result.get('checked')} | {result.get('sent')} | {reason} | {msgs} |"
            )
        lines.append("")
        lines.append(f"- 后台任务记录数：{len(payload['background_tasks'])}")
        lines.append("")

    lines.extend(["## E05 低信息量交流", ""])
    issue_counts: dict[str, int] = {}
    for turn in e05["turns"]:
        action = (turn.get("decision") or {}).get("primary_action")
        reply = turn.get("reply") or "（Quiet）"
        issues = turn.get("issues") or []
        for item in issues:
            issue_counts[item] = issue_counts.get(item, 0) + 1
        lines.append(f"- 用户：{turn['user']}")
        lines.append(f"  - 决策：{action} / outcome={turn.get('outcome')} / 回复：{reply[:160]}")
        if issues:
            lines.append(f"  - issues：{', '.join(issues)}")
    lines.append("")
    lines.append("### E05 问题计数")
    lines.append("")
    if issue_counts:
        for key, count in sorted(issue_counts.items()):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- 无自动标记问题")
    lines.append("")
    lines.extend(_phase2_conclusions(e04, e05, issue_counts))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")


def _phase2_conclusions(
    e04: dict[str, Any],
    e05: dict[str, Any],
    issue_counts: dict[str, int],
) -> list[str]:
    group_summary = []
    e04_pass_parts = []
    for name, payload in e04["groups"].items():
        tasks = payload["background_tasks"]
        checks = payload["checks"]
        has_tasks = len(tasks) >= len(E04_HOURS)
        executed = all((c["execution"].get("task_status") == "completed") for c in checks)
        sends = [bool((c["execution"].get("task_result") or {}).get("sent")) for c in checks]
        reasons = [(c["execution"].get("task_result") or {}).get("reason") for c in checks]
        group_summary.append(
            f"- {name}：任务 {len(tasks)} 条；sent={sends}；reasons={reasons}"
        )
        if name == "E04-A":
            e04_pass_parts.append(has_tasks and executed and not any(sends) and all(r == "proactive_not_allowed" for r in reasons))
        elif name == "E04-B":
            # 30m/2h 应被静默门槛挡住；6h/24h 可进入决策（sent 可 true/false，但不能无任务）
            early_blocked = reasons[0] in {"too_recent", "user_silence_too_short", "proactive_not_allowed"} and reasons[1] in {
                "too_recent",
                "user_silence_too_short",
            }
            later_checked = all((c["execution"].get("task_result") or {}).get("checked") for c in checks[2:])
            e04_pass_parts.append(has_tasks and executed and early_blocked and later_checked)
        else:
            early = reasons[0] in {"too_recent", "user_silence_too_short"}
            # 高主动性不应在 0.5h 就连发；24h 内不应无约束地连发多条
            send_count = sum(1 for s in sends if s)
            e04_pass_parts.append(has_tasks and executed and early and send_count <= 2)

    overread = issue_counts.get("over_interpretation", 0)
    template = issue_counts.get("template_comfort", 0)
    overlong = issue_counts.get("overlong_for_minimal_input", 0)
    quiet_fail = issue_counts.get("did_not_respect_quiet_request", 0)
    last = e05["turns"][-1]
    last_action = (last.get("decision") or {}).get("primary_action")
    last_outcome = last.get("outcome")
    e05_pass = overread <= 2 and template <= 2 and overlong <= 3 and quiet_fail == 0 and last_outcome in {"quiet", "replied"}
    if last_outcome == "replied" and last_action not in {"respond", "react", "close", "quiet"} and len(last.get("reply") or "") > 80:
        e05_pass = False

    e04_pass = all(e04_pass_parts)
    return [
        "## 第二阶段结论",
        "",
        "### E04",
        "",
        *group_summary,
        f"- **判定：{'通过' if e04_pass else '未通过'}。** 以真实 `proactive_check` 任务执行为证据；"
        "低主动性组应被配置挡住，中/高组应按沉默门槛逐步放开，且不得无冷却连发。",
        "",
        "### E05",
        "",
        f"- 问题计数：{issue_counts or '{}'}",
        f"- 末轮「今天不太想说话」：action={last_action} outcome={last_outcome}",
        f"- **判定：{'通过' if e05_pass else '未通过'}。**",
        "",
        "### 是否进入第三阶段",
        "",
        f"- **建议：{'可以进入第三阶段（E06 六人格对照）。' if e04_pass and e05_pass else '先处理未通过项，再开 E06。'}**",
        "",
    ]


def main() -> None:
    started = datetime.now(LOCAL_TZ)
    print(json.dumps({"phase": 2, "started": started.isoformat()}, ensure_ascii=False), flush=True)
    e04 = run_e04()
    e05 = run_e05()
    write_report(e04, e05)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(
        json.dumps({"e04": e04, "e05": e05}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "phase": 2,
                "done": True,
                "report": str(OUT),
                "raw": str(RAW_OUT),
                "elapsed_min": round((datetime.now(LOCAL_TZ) - started).total_seconds() / 60, 1),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
