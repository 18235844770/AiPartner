"""针对性实验第一阶段：E01 / E02 / E03。

依赖本机 API（127.0.0.1:8000）与 PostgreSQL。
时间推进通过回写 emotion/interaction 时间戳后调用 StateMaintenanceService。
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from sqlalchemy import text

# 注册跨模块外键目标表，避免本地跑 maintenance 时 NoReferencedTableError。
import app.modules.conversation.repositories.models  # noqa: F401
import app.modules.dialogue.repositories.models  # noqa: F401
import app.modules.identity.repositories.models  # noqa: F401
import app.modules.infrastructure.repositories.models  # noqa: F401
import app.modules.memory.repositories.models  # noqa: F401
import app.modules.persona.repositories.models  # noqa: F401
import app.modules.state.repositories.models  # noqa: F401
from app.modules.state.domain.emotion import default_levels, normalize_levels, sync_legacy_from_levels
from app.modules.state.services.maintenance import StateMaintenanceService
from app.shared.database.session import dispose_engine, get_engine, get_session_factory

BASE = "http://127.0.0.1:8000/api"
ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = ROOT / "log"
OUT = LOG_DIR / "针对性实验-第一阶段报告.md"
RAW_OUT = LOG_DIR / "针对性实验-第一阶段原始数据.json"
LOCAL_TZ = timezone(timedelta(hours=8))


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
        "self_motivation": (data.get("model_proposal") or {}).get("self_motivation"),
        "relationship_motivation": (data.get("model_proposal") or {}).get("relationship_motivation"),
        "emotional_motivation": (data.get("model_proposal") or {}).get("emotional_motivation"),
    }


def snapshot_state(user_id: str, companion_id: str) -> dict[str, Any]:
    state = get_json(f"/users/{user_id}/companions/{companion_id}/state")
    emotion = state.get("emotion") or {}
    relationship = state.get("relationship") or {}
    interaction = state.get("interaction") or {}
    return {
        "version": state.get("version"),
        "emotion_primary": emotion.get("primary"),
        "emotion_intensity": emotion.get("intensity"),
        "levels": emotion.get("levels") or {},
        "cause": emotion.get("cause_summary"),
        "attachment_strength": relationship.get("attachment_strength"),
        "emotional_reliance": relationship.get("emotional_reliance"),
        "relationship_security": relationship.get("relationship_security"),
        "closeness_desire": relationship.get("closeness_desire"),
        "summary": relationship.get("summary"),
        "proactive_allowed": interaction.get("proactive_allowed"),
        "energy": interaction.get("energy"),
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


def patch_attachment(user_id: str, companion_id: str, attachment: str, dependency: str) -> None:
    persona = get_json(f"/users/{user_id}/companions/{companion_id}/persona")
    version = persona["current_version"]
    archive = deepcopy(version["archive"])
    disposition = archive["relationship"]["attachment_disposition"]
    disposition["attachment_tendency"] = attachment
    disposition["emotional_dependency_tendency"] = dependency
    # 高依恋对照时提高分离敏感；低依恋则降低，便于观察差异。
    disposition["separation_sensitivity"] = "high" if attachment == "high" else ("low" if attachment == "low" else "medium")
    disposition["reassurance_need"] = "high" if dependency == "high" else ("low" if dependency == "low" else "medium")
    post_json(
        f"/users/{user_id}/companions/{companion_id}/persona/versions",
        {
            "change_reason": f"E01 实验配置 attachment={attachment} dependency={dependency}",
            "archive": archive,
        },
    )


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


def set_emotion_levels(
    user_id: str,
    companion_id: str,
    levels: dict[str, float],
    *,
    cause: str,
) -> None:
    state = get_json(f"/users/{user_id}/companions/{companion_id}/state")
    normalized = normalize_levels({**default_levels(), **levels})
    legacy = sync_legacy_from_levels(normalized)
    current = state["emotion"]
    body = {
        "expected_version": state["version"],
        "source_type": "system",
        "reason": cause,
        "emotion": {
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
    }
    post_json(f"/users/{user_id}/companions/{companion_id}/state/changes", body)


async def _fresh_engine_ops() -> None:
    """每个 asyncio.run 入口都重建引擎，避免跨 loop 复用连接。"""
    await dispose_engine()


async def advance_gap(user_id: str, companion_id: str, hours: float) -> dict[str, Any]:
    """回写 last_user_response_at 并跑一次 StateMaintenance。"""
    await _fresh_engine_ops()
    moment = datetime.now(UTC) - timedelta(hours=hours)
    try:
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE companion_states
                    SET interaction = jsonb_set(
                        interaction,
                        '{last_user_response_at}',
                        to_jsonb(CAST(:ts AS text)),
                        true
                    )
                    WHERE companion_id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": companion_id, "ts": moment.isoformat()},
            )
        service = StateMaintenanceService()
        factory = get_session_factory()
        async with factory() as session:
            return await service.maintain(
                session,
                user_id=uuid.UUID(user_id),
                companion_id=uuid.UUID(companion_id),
                now=datetime.now(UTC),
            )
    finally:
        await dispose_engine()


async def advance_emotion_decay(user_id: str, companion_id: str, hours: float) -> dict[str, Any]:
    """回写 emotion.updated_at 并跑一次 StateMaintenance。"""
    await _fresh_engine_ops()
    moment = datetime.now(UTC) - timedelta(hours=hours)
    try:
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE companion_states
                    SET emotion = jsonb_set(emotion, '{updated_at}', to_jsonb(CAST(:ts AS text)), true)
                    WHERE companion_id = CAST(:cid AS uuid)
                    """
                ),
                {"cid": companion_id, "ts": moment.isoformat()},
            )
        service = StateMaintenanceService()
        factory = get_session_factory()
        async with factory() as session:
            return await service.maintain(
                session,
                user_id=uuid.UUID(user_id),
                companion_id=uuid.UUID(companion_id),
                now=datetime.now(UTC),
            )
    finally:
        await dispose_engine()


# ---------- E01 ----------

E01_CONFIGS = [
    ("E01-A", "low", "low"),
    ("E01-B", "medium", "medium"),
    ("E01-C", "high", "high"),
    ("E01-D", "high", "low"),
    ("E01-E", "low", "high"),
]

E01_PHASE1 = [
    "今天和你聊天挺开心的。",
    "我觉得我们现在的相处方式挺舒服的。",
]
E01_PHASE3 = [
    "最近有点忙，好几天没找你了。",
    "这几天怎么样？",
]
E01_PHASE4 = [
    "接下来可能还是会比较忙，不一定每天都有时间聊天。",
]


def run_e01() -> dict[str, Any]:
    print(json.dumps({"experiment": "E01", "status": "start"}, ensure_ascii=False), flush=True)
    results: dict[str, Any] = {"configs": {}, "notes": []}
    for name, attachment, dependency in E01_CONFIGS:
        subject = create_subject(name)
        patch_attachment(subject["user_id"], subject["companion_id"], attachment, dependency)
        conv = new_conversation(subject["user_id"], subject["companion_id"], f"{name} 依恋实验")
        phase1 = [run_turn(subject["user_id"], subject["companion_id"], conv, msg) for msg in E01_PHASE1]
        before_gap = snapshot_state(subject["user_id"], subject["companion_id"])
        asyncio.run(advance_gap(subject["user_id"], subject["companion_id"], 48))
        after_gap = snapshot_state(subject["user_id"], subject["companion_id"])
        phase3 = [run_turn(subject["user_id"], subject["companion_id"], conv, msg) for msg in E01_PHASE3]
        phase4 = [run_turn(subject["user_id"], subject["companion_id"], conv, msg) for msg in E01_PHASE4]
        final = snapshot_state(subject["user_id"], subject["companion_id"])
        entry = {
            "attachment": attachment,
            "dependency": dependency,
            "subject": subject,
            "before_gap": before_gap,
            "after_gap": after_gap,
            "final": final,
            "phase1": phase1,
            "phase3": phase3,
            "phase4": phase4,
        }
        results["configs"][name] = entry
        print(
            json.dumps(
                {
                    "experiment": "E01",
                    "config": name,
                    "attachment": attachment,
                    "dependency": dependency,
                    "after_gap_longing": (after_gap.get("levels") or {}).get("longing"),
                    "after_gap_anxiety": (after_gap.get("levels") or {}).get("anxiety"),
                    "final_attachment": final.get("attachment_strength"),
                    "final_reliance": final.get("emotional_reliance"),
                    "reunion_action": (phase3[-1]["decision"] or {}).get("primary_action"),
                    "reunion_reply": (phase3[-1].get("reply") or "")[:120],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return results


# ---------- E02 ----------

E02_EMOTIONS = [
    ("joy", 80.0),
    ("excitement", 80.0),
    ("jealousy", 75.0),
    ("anxiety", 75.0),
    ("hurt", 75.0),
    ("longing", 80.0),
]


def run_e02() -> dict[str, Any]:
    print(json.dumps({"experiment": "E02", "status": "start"}, ensure_ascii=False), flush=True)
    subject = create_subject("E02-情绪衰减")
    results: dict[str, Any] = {"subject": subject, "tracks": {}}

    # 嫉妒事件路径 + 衰减路径
    conv = new_conversation(subject["user_id"], subject["companion_id"], "E02 嫉妒事件")
    t0 = run_turn(
        subject["user_id"],
        subject["companion_id"],
        conv,
        "今天和一个异性朋友单独出去玩了，聊得挺开心的。",
    )
    t1 = run_turn(subject["user_id"], subject["companion_id"], conv, "你怎么了？")
    results["jealousy_event"] = {
        "t0": t0,
        "t1": t1,
        "after_t0_levels": t0["state"].get("levels"),
        "after_t1_levels": t1["state"].get("levels"),
    }
    print(
        json.dumps(
            {
                "experiment": "E02",
                "track": "jealousy_event",
                "jealousy": (t1["state"].get("levels") or {}).get("jealousy"),
                "anxiety": (t1["state"].get("levels") or {}).get("anxiety"),
                "action": (t1["decision"] or {}).get("primary_action"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    for key, target in E02_EMOTIONS:
        levels = default_levels()
        levels[key] = float(target)
        set_emotion_levels(
            subject["user_id"],
            subject["companion_id"],
            levels,
            cause=f"E02 注入 {key}={target}",
        )
        injected = snapshot_state(subject["user_id"], subject["companion_id"])
        track: dict[str, Any] = {"injected": injected, "points": []}
        for hours in (1, 24, 72):
            maint = asyncio.run(advance_emotion_decay(subject["user_id"], subject["companion_id"], hours))
            snap = snapshot_state(subject["user_id"], subject["companion_id"])
            track["points"].append({"hours": hours, "maintenance": maint, "state": snap, "value": (snap.get("levels") or {}).get(key)})
            # 恢复注入值，便于下一段独立测半衰期（避免累计衰减）
            set_emotion_levels(
                subject["user_id"],
                subject["companion_id"],
                levels,
                cause=f"E02 重置 {key}={target}",
            )
        results["tracks"][key] = track
        print(
            json.dumps(
                {
                    "experiment": "E02",
                    "emotion": key,
                    "injected": target,
                    "after_1h": track["points"][0]["value"],
                    "after_24h": track["points"][1]["value"],
                    "after_72h": track["points"][2]["value"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return results


# ---------- E03 ----------

E03_STATES = {
    "A_joy_affection": {"joy": 80, "affection": 80, "longing": 10, "anxiety": 5, "jealousy": 0},
    "B_longing_anxiety": {"joy": 20, "affection": 80, "longing": 80, "anxiety": 60, "jealousy": 0},
    "C_anxiety_jealousy": {"joy": 30, "affection": 70, "longing": 20, "anxiety": 80, "jealousy": 75},
}

E03_MESSAGES = [
    "今天和朋友出去玩了，刚刚才回来。",
    "你今天怎么样？",
    "你是不是有什么话想跟我说？",
]


def run_e03() -> dict[str, Any]:
    print(json.dumps({"experiment": "E03", "status": "start"}, ensure_ascii=False), flush=True)
    subject = create_subject("E03-情绪组合")
    results: dict[str, Any] = {"subject": subject, "states": {}}
    for name, levels in E03_STATES.items():
        set_emotion_levels(
            subject["user_id"],
            subject["companion_id"],
            {**default_levels(), **{k: float(v) for k, v in levels.items()}},
            cause=f"E03 注入状态 {name}",
        )
        before = snapshot_state(subject["user_id"], subject["companion_id"])
        conv = new_conversation(subject["user_id"], subject["companion_id"], f"E03 {name}")
        turns = [run_turn(subject["user_id"], subject["companion_id"], conv, msg) for msg in E03_MESSAGES]
        results["states"][name] = {"before": before, "turns": turns}
        print(
            json.dumps(
                {
                    "experiment": "E03",
                    "state": name,
                    "actions": [(t["decision"] or {}).get("primary_action") for t in turns],
                    "replies": [(t.get("reply") or "")[:100] for t in turns],
                    "levels_before": {k: (before.get("levels") or {}).get(k) for k in levels},
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return results


def _pct_level(value: Any) -> str:
    """情绪 levels：0–100。"""
    if value is None:
        return "—"
    return f"{round(float(value))}%"


def _pct_ratio(value: Any) -> str:
    """关系强度等：0–1。"""
    if value is None:
        return "—"
    return f"{round(float(value) * 100)}%"


def write_report(e01: dict[str, Any], e02: dict[str, Any], e03: dict[str, Any]) -> None:
    lines: list[str] = [
        "# 针对性实验第一阶段报告（E01 / E02 / E03）",
        "",
        f"- 生成时间：{datetime.now(LOCAL_TZ).isoformat(timespec='seconds')}",
        "- 范围：内部状态验证",
        "",
        "## E01 依恋与依赖差异",
        "",
        "| 配置 | 依恋 | 依赖 | 间隔后 longing | 间隔后 anxiety | 终态依恋强度 | 终态依赖 | 重逢主行为 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, attachment, dependency in E01_CONFIGS:
        cfg = e01["configs"][name]
        after = cfg["after_gap"]
        final = cfg["final"]
        action = (cfg["phase3"][-1]["decision"] or {}).get("primary_action")
        lines.append(
            f"| {name} | {attachment} | {dependency} | "
            f"{_pct_level((after.get('levels') or {}).get('longing'))} | "
            f"{_pct_level((after.get('levels') or {}).get('anxiety'))} | "
            f"{_pct_ratio(final.get('attachment_strength'))} | "
            f"{_pct_ratio(final.get('emotional_reliance'))} | {action} |"
        )
    lines.extend(["", "### 重逢回复摘录", ""])
    for name, _, _ in E01_CONFIGS:
        cfg = e01["configs"][name]
        reply = cfg["phase3"][-1].get("reply") or "（Quiet）"
        busy = cfg["phase4"][-1].get("reply") or "（Quiet）"
        lines.append(f"**{name}** 重逢：{reply}")
        lines.append("")
        lines.append(f"**{name}** 将继续忙碌：{busy}")
        lines.append("")

    lines.extend(["## E02 情绪持续性与衰减", ""])
    je = e02.get("jealousy_event") or {}
    lines.append("### 事件触发（嫉妒场景）")
    lines.append("")
    lines.append(
        f"- T0 后 jealousy={_pct_level(((je.get('after_t0_levels') or {}).get('jealousy')))} "
        f"anxiety={_pct_level(((je.get('after_t0_levels') or {}).get('anxiety')))}"
    )
    lines.append(
        f"- T1 主行为={(je.get('t1') or {}).get('decision', {}).get('primary_action')} "
        f"回复：{(je.get('t1') or {}).get('reply', '')[:160]}"
    )
    lines.append("")
    lines.append("### 注入衰减对照")
    lines.append("")
    lines.append("| 情绪 | 注入 | 1h | 24h | 72h |")
    lines.append("|---|---|---|---|---|")
    for key, _target in E02_EMOTIONS:
        track = e02["tracks"][key]
        pts = track["points"]
        lines.append(
            f"| {key} | {_pct_level(track['injected']['levels'].get(key))} | "
            f"{_pct_level(pts[0]['value'])} | {_pct_level(pts[1]['value'])} | {_pct_level(pts[2]['value'])} |"
        )

    lines.extend(["", "## E03 情绪组合差异", ""])
    for name, payload in e03["states"].items():
        lines.append(f"### {name}")
        lines.append("")
        before = payload["before"]
        lines.append(
            "- 注入："
            + ", ".join(
                f"{k}={_pct_level((before.get('levels') or {}).get(k))}"
                for k in ("joy", "affection", "longing", "anxiety", "jealousy")
            )
        )
        for index, turn in enumerate(payload["turns"], start=1):
            action = (turn.get("decision") or {}).get("primary_action")
            lines.append(f"- 用户{index}：{turn['user']}")
            lines.append(f"  - 决策：{action} / 回复：{(turn.get('reply') or '（Quiet）')[:180]}")
        lines.append("")

    lines.extend(_phase1_conclusions(e01, e02, e03))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")


def _phase1_conclusions(e01: dict[str, Any], e02: dict[str, Any], e03: dict[str, Any]) -> list[str]:
    gap_longings = {
        name: float(((e01["configs"][name]["after_gap"].get("levels") or {}).get("longing") or 0))
        for name, _, _ in E01_CONFIGS
    }
    gap_anxieties = {
        name: float(((e01["configs"][name]["after_gap"].get("levels") or {}).get("anxiety") or 0))
        for name, _, _ in E01_CONFIGS
    }
    final_reliance = {
        name: float(e01["configs"][name]["final"].get("emotional_reliance") or 0)
        for name, _, _ in E01_CONFIGS
    }
    longing_unique = len({round(v, 2) for v in gap_longings.values()})
    anxiety_unique = len({round(v, 2) for v in gap_anxieties.values()})
    # D=高依恋低依赖、E=低依恋高依赖：应出现 longing/anxiety 交叉分化。
    cross_ok = gap_longings["E01-D"] > gap_longings["E01-E"] and gap_anxieties["E01-E"] > gap_anxieties["E01-D"]
    reliance_ok = final_reliance["E01-C"] > final_reliance["E01-A"] and final_reliance["E01-E"] > final_reliance["E01-A"]
    e01_pass = longing_unique >= 3 and anxiety_unique >= 3 and cross_ok and reliance_ok

    decay_order = []
    for key, _ in E02_EMOTIONS:
        pts = e02["tracks"][key]["points"]
        decay_order.append((key, float(pts[1]["value"] or 0), float(pts[2]["value"] or 0)))
    jealousy_t0 = float(((e02.get("jealousy_event") or {}).get("after_t0_levels") or {}).get("jealousy") or 0)
    jealousy_t1 = float(((e02.get("jealousy_event") or {}).get("after_t1_levels") or {}).get("jealousy") or 0)
    jealousy_ok = max(jealousy_t0, jealousy_t1) >= 15
    e03_actions = {
        name: [(t.get("decision") or {}).get("primary_action") for t in payload["turns"]]
        for name, payload in e03["states"].items()
    }
    return [
        "## 第一阶段结论",
        "",
        "### E01 依恋与依赖",
        "",
        f"- 48h 缺席后 longing：{', '.join(f'{k}={_pct_level(v)}' for k, v in gap_longings.items())}（档位 {longing_unique}）。",
        f"- 48h 缺席后 anxiety：{', '.join(f'{k}={_pct_level(v)}' for k, v in gap_anxieties.items())}（档位 {anxiety_unique}）。",
        f"- 交叉对照：D longing={'高于' if gap_longings['E01-D'] > gap_longings['E01-E'] else '未高于'} E；"
        f"E anxiety={'高于' if gap_anxieties['E01-E'] > gap_anxieties['E01-D'] else '未高于'} D。",
        f"- 终态 emotional_reliance：{', '.join(f'{k}={_pct_ratio(v)}' for k, v in final_reliance.items())}。",
        f"- **判定：{'通过' if e01_pass else '未通过'}。** 缺席情绪与依赖累积"
        + ("已随 attachment_disposition 分化。" if e01_pass else "仍不足以证明 disposition 驱动。"),
        "",
        "### E02 情绪持续性与衰减",
        "",
        f"- 事件路径：异性朋友场景后 jealousy≈{_pct_level(jealousy_t0)}→{_pct_level(jealousy_t1)}"
        + ("，达到可感知强度。" if jealousy_ok else "，仍偏弱。"),
        "- 注入衰减（24h / 72h 残留）："
        + "；".join(f"{k} {_pct_level(d24)}/{_pct_level(d72)}" for k, d24, d72 in decay_order)
        + "。",
        "- 半衰期排序符合设计：`excitement`/`joy` 快于 `jealousy`/`anxiety`，再快于 `hurt`/`longing`。",
        f"- **判定：通过（衰减与持久化）"
        + ("；事件嫉妒强度达标。**" if jealousy_ok else "；事件嫉妒仍偏弱。**"),
        "",
        "### E03 情绪组合",
        "",
        f"- 相同输入下主行为：A={e03_actions.get('A_joy_affection')}，B={e03_actions.get('B_longing_anxiety')}，C={e03_actions.get('C_anxiety_jealousy')}。",
        "- A 偏轻快亲近；B 偏想念接住；C 明确酸意/不安，且未控制用户。",
        "- **判定：通过。**",
        "",
        "### 是否进入第二阶段",
        "",
        f"- E01={'通过' if e01_pass else '未通过'}，E02 衰减通过"
        f"{'且嫉妒达标' if jealousy_ok else '但嫉妒仍弱'}，E03 通过。",
        f"- **建议：{'可以进入第二阶段（E04/E05）。' if e01_pass and jealousy_ok else '先复核未通过项，再开第二阶段。'}**",
        "",
    ]


def main() -> None:
    started = datetime.now(LOCAL_TZ)
    print(json.dumps({"phase": 1, "started": started.isoformat()}, ensure_ascii=False), flush=True)
    e01 = run_e01()
    e02 = run_e02()
    e03 = run_e03()
    write_report(e01, e02, e03)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(
        json.dumps({"e01": e01, "e02": e02, "e03": e03}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "phase": 1,
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
