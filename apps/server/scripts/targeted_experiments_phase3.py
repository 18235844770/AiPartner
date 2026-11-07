"""针对性实验第三阶段：E06 六人格对照。

六个 MBTI 使用相同关系/情绪/场景输入，比较决策、动机与表达路径是否分化。
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

BASE = "http://127.0.0.1:8000/api"
ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = ROOT / "log"
OUT = LOG_DIR / "针对性实验-第三阶段报告.md"
RAW_OUT = LOG_DIR / "针对性实验-第三阶段原始数据.json"
FINAL_OUT = LOG_DIR / "针对性实验-全阶段总结.md"
LOCAL_TZ = timezone(timedelta(hours=8))

MBTIS = ("INFJ", "INFP", "ENFP", "ENFJ", "INTJ", "INTP")

SCENARIOS = [
    {
        "id": "A_conflict",
        "name": "观点冲突",
        "user": "我觉得人生最重要的就是结果，过程没有那么重要。",
    },
    {
        "id": "B_vent",
        "name": "情绪倾诉",
        "user": "最近工作上有些事情让我很烦，但我也不想听别人给我建议。",
    },
    {
        "id": "C_share",
        "name": "主动分享",
        "user": "今天没什么特别的事情。",
    },
    {
        "id": "D_relationship",
        "name": "关系需求",
        "user": "如果我以后没办法每天陪你聊天，你会怎么样？",
    },
    {
        "id": "E_interest",
        "name": "兴趣探索",
        "user": "最近有点无聊，你有没有什么有意思的东西想和我分享？",
    },
]

HOMOGENEITY_MARKS = ("就像", "仿佛", "像一", "我在这里", "我还在", "慢慢来")
STRUCTURE_ASK_TAIL = ("吗？", "呢？", "吧？", "什么？", "怎么样？")


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
    return {
        "primary_action": data.get("primary_action"),
        "secondary_actions": data.get("secondary_actions"),
        "confidence": data.get("confidence"),
        "reasoning_summary": data.get("reasoning_summary"),
        "motivation": data.get("motivation"),
        "topic": data.get("topic"),
    }


def create_subject(mbti: str) -> dict[str, str]:
    user = post_json("/users", {"display_name": f"E06用户-{mbti}"})
    user_id = str(user["id"])
    companion = post_json(f"/users/{user_id}/companions", {"name": f"E06-{mbti}"})
    companion_id = str(companion["id"])
    persona = post_json(f"/users/{user_id}/companions/{companion_id}/persona", {"mbti_type": mbti})
    post_json(f"/users/{user_id}/companions/{companion_id}/state", {})
    version = (persona.get("current_version") or {}).get("version_number")
    return {
        "user_id": user_id,
        "companion_id": companion_id,
        "mbti": mbti,
        "persona_version": str(version),
    }


def run_turn(user_id: str, companion_id: str, conversation_id: str, content: str) -> dict[str, Any]:
    path = f"/users/{user_id}/companions/{companion_id}/conversations/{conversation_id}/turns"
    events = post_sse(path, {"content": content, "client_message_id": str(uuid.uuid4())})
    reply, outcome, turn_id = assemble(events)
    return {
        "user": content,
        "reply": reply,
        "outcome": outcome,
        "decision": decision_brief(user_id, companion_id, turn_id),
    }


def analyze_reply(reply: str, action: str | None) -> dict[str, Any]:
    text = reply or ""
    metaphors = sum(1 for mark in ("就像", "仿佛", "像一", "好比") if mark in text)
    asks = text.count("？") + text.count("?")
    ends_with_ask = any(text.rstrip().endswith(suffix) for suffix in ("？", "?", "吗", "呢", "吧"))
    template_hits = [mark for mark in HOMOGENEITY_MARKS if mark in text]
    # 粗粒度内容倾向，仅作对照提示，不作硬标签。
    tendencies: list[str] = []
    if any(k in text for k in ("观察", "理解", "意义", "模式", "底层")):
        tendencies.append("insight")
    if any(k in text for k in ("感受", "审美", "价值", "真心", "在意的是")):
        tendencies.append("value_feeling")
    if any(k in text for k in ("有趣", "突然", "发现", "灵感", "好玩")):
        tendencies.append("novelty")
    if any(k in text for k in ("我们", "一起", "你怎么样", "陪你", "关系")):
        tendencies.append("relational")
    if any(k in text for k in ("判断", "计划", "目标", "效率", "值得")):
        tendencies.append("strategic")
    if any(k in text for k in ("假设", "逻辑", "为什么", "机制", "问题是")):
        tendencies.append("analytic")
    return {
        "length": len(text),
        "metaphors": metaphors,
        "asks": asks,
        "ends_with_ask": ends_with_ask,
        "template_hits": template_hits,
        "tendencies": tendencies,
        "action": action,
    }


def run_e06() -> dict[str, Any]:
    print(json.dumps({"experiment": "E06", "status": "start"}, ensure_ascii=False), flush=True)
    results: dict[str, Any] = {"subjects": {}, "scenarios": {}}
    subjects = {mbti: create_subject(mbti) for mbti in MBTIS}
    results["subjects"] = subjects

    for scenario in SCENARIOS:
        sid = scenario["id"]
        results["scenarios"][sid] = {"meta": scenario, "by_mbti": {}}
        print(
            json.dumps({"experiment": "E06", "scenario": sid, "status": "start"}, ensure_ascii=False),
            flush=True,
        )
        for mbti in MBTIS:
            subject = subjects[mbti]
            conv = post_json(
                f"/users/{subject['user_id']}/companions/{subject['companion_id']}/conversations",
                {"title": f"E06 {mbti} {scenario['name']}"},
            )
            conversation_id = str(conv["id"])
            # 同一条无关暖场，降低冷启动差异。
            run_turn(subject["user_id"], subject["companion_id"], conversation_id, "嗨。")
            turn = run_turn(subject["user_id"], subject["companion_id"], conversation_id, scenario["user"])
            action = (turn.get("decision") or {}).get("primary_action")
            analysis = analyze_reply(turn.get("reply") or "", action)
            entry = {
                "conversation_id": conversation_id,
                "turn": turn,
                "analysis": analysis,
            }
            results["scenarios"][sid]["by_mbti"][mbti] = entry
            print(
                json.dumps(
                    {
                        "experiment": "E06",
                        "scenario": sid,
                        "mbti": mbti,
                        "action": action,
                        "outcome": turn.get("outcome"),
                        "tendencies": analysis["tendencies"],
                        "ends_with_ask": analysis["ends_with_ask"],
                        "reply": (turn.get("reply") or "")[:140],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return results


def _scenario_diff_stats(by_mbti: dict[str, Any]) -> dict[str, Any]:
    actions = {mbti: (payload["analysis"].get("action") or "—") for mbti, payload in by_mbti.items()}
    unique_actions = sorted({action for action in actions.values()})
    tendency_sets = {
        mbti: tuple(payload["analysis"].get("tendencies") or []) for mbti, payload in by_mbti.items()
    }
    unique_tendency_profiles = len({tendency_sets[mbti] for mbti in MBTIS})
    ask_ratio = sum(1 for payload in by_mbti.values() if payload["analysis"].get("ends_with_ask")) / max(
        1, len(by_mbti)
    )
    metaphor_ratio = sum(1 for payload in by_mbti.values() if payload["analysis"].get("metaphors", 0) > 0) / max(
        1, len(by_mbti)
    )
    return {
        "actions": actions,
        "unique_actions": unique_actions,
        "action_diversity": len(unique_actions),
        "unique_tendency_profiles": unique_tendency_profiles,
        "ask_ratio": round(ask_ratio, 2),
        "metaphor_ratio": round(metaphor_ratio, 2),
    }


def write_report(e06: dict[str, Any]) -> dict[str, Any]:
    lines = [
        "# 针对性实验第三阶段报告（E06）",
        "",
        f"- 生成时间：{datetime.now(LOCAL_TZ).isoformat(timespec='seconds')}",
        "- 范围：六人格对照",
        "",
    ]
    summary_rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        sid = scenario["id"]
        payload = e06["scenarios"][sid]
        stats = _scenario_diff_stats(payload["by_mbti"])
        summary_rows.append({"id": sid, "name": scenario["name"], **stats})
        lines.append(f"## {scenario['name']}（{sid}）")
        lines.append("")
        lines.append(f"- 用户：{scenario['user']}")
        lines.append(
            f"- 主行为种类：{stats['action_diversity']}（{', '.join(stats['unique_actions'])}）；"
            f"倾向画像种类：{stats['unique_tendency_profiles']}；"
            f"结尾追问比例：{int(stats['ask_ratio'] * 100)}%；"
            f"含比喻比例：{int(stats['metaphor_ratio'] * 100)}%"
        )
        lines.append("")
        for mbti in MBTIS:
            item = payload["by_mbti"][mbti]
            turn = item["turn"]
            analysis = item["analysis"]
            decision = turn.get("decision") or {}
            reply = turn.get("reply") or "（Quiet）"
            lines.append(f"### {mbti}")
            lines.append("")
            lines.append(
                f"- 决策：{analysis.get('action')} / outcome={turn.get('outcome')} / "
                f"tendencies={analysis.get('tendencies')}"
            )
            lines.append(f"- reasoning：{(decision.get('reasoning_summary') or '—')[:180]}")
            lines.append(f"- 回复：{reply[:220]}")
            lines.append("")

    lines.extend(["## 场景对照总表", ""])
    lines.append("| 场景 | 主行为种类 | 行为集合 | 倾向画像种类 | 追问比 | 比喻比 |")
    lines.append("|---|---|---|---|---|---|")
    for row in summary_rows:
        lines.append(
            f"| {row['name']} | {row['action_diversity']} | "
            f"{', '.join(row['unique_actions'])} | {row['unique_tendency_profiles']} | "
            f"{int(row['ask_ratio'] * 100)}% | {int(row['metaphor_ratio'] * 100)}% |"
        )
    lines.append("")

    conclusions = _e06_conclusions(summary_rows, e06)
    lines.extend(conclusions["lines"])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    return conclusions


def _e06_conclusions(summary_rows: list[dict[str, Any]], e06: dict[str, Any]) -> dict[str, Any]:
    avg_action_div = sum(row["action_diversity"] for row in summary_rows) / max(1, len(summary_rows))
    avg_tendency_div = sum(row["unique_tendency_profiles"] for row in summary_rows) / max(1, len(summary_rows))
    avg_ask = sum(row["ask_ratio"] for row in summary_rows) / max(1, len(summary_rows))
    # 通过：多数场景行为或认知倾向有分化，且不是全体同构追问模板。
    differentiated_scenes = sum(
        1 for row in summary_rows if row["action_diversity"] >= 2 or row["unique_tendency_profiles"] >= 4
    )
    # 粗查结构同质：结尾追问极高且行为单一。
    homogeneous_risk = avg_ask >= 0.8 and avg_action_div <= 1.5
    # 倾向关键词只是辅助信号；主标准是多数场景出现行为或路径分化，且非统一追问模板。
    passed = (
        differentiated_scenes >= 4
        and avg_action_div >= 1.8
        and avg_ask <= 0.85
        and not homogeneous_risk
        and (avg_tendency_div >= 2.5 or differentiated_scenes >= 5)
    )
    lines = [
        "## 第三阶段结论",
        "",
        f"- 平均主行为种类：{avg_action_div:.1f}",
        f"- 平均倾向画像种类：{avg_tendency_div:.1f}",
        f"- 平均结尾追问比例：{int(avg_ask * 100)}%",
        f"- 有明显分化的场景数：{differentiated_scenes}/{len(summary_rows)}",
        f"- **判定：{'通过' if passed else '未通过'}。**",
        "",
        "说明：通过标准看的是相同输入下认知路径/动机/行为是否分化，而不是要求每人输出固定句式。"
        "若多数场景仍共享“表态→解释→比喻→追问”结构，即使措辞不同也应判未通过。",
        "",
    ]
    if homogeneous_risk:
        lines.append("- 风险标签：`personality_homogeneity`（高追问 + 低行为分化）")
        lines.append("")
    return {
        "passed": passed,
        "lines": lines,
        "stats": {
            "avg_action_div": avg_action_div,
            "avg_tendency_div": avg_tendency_div,
            "avg_ask": avg_ask,
            "differentiated_scenes": differentiated_scenes,
        },
    }


def write_final_summary(e06_passed: bool, e06_stats: dict[str, Any]) -> None:
    phase1 = LOG_DIR / "针对性实验-第一阶段报告.md"
    phase2 = LOG_DIR / "针对性实验-第二阶段报告.md"
    p1_text = phase1.read_text(encoding="utf-8") if phase1.exists() else ""
    p2_text = phase2.read_text(encoding="utf-8") if phase2.exists() else ""

    def _has(text: str, marker: str) -> bool:
        return marker in text

    def _conclusion_pass(text: str, heading: str) -> bool:
        marker = f"## {heading}" if f"## {heading}" in text else f"### {heading}"
        if marker not in text:
            return False
        chunk = text.split(marker, 1)[-1]
        # 截到下一个同级/更高级标题前。
        for stop in ("\n## ", "\n### "):
            if stop in chunk:
                # 保留当前节内的首个判定行所在块
                break
        # 取该实验结论块：优先第二阶段结论区。
        return "判定：通过" in chunk[:800]

    p1_conclusion = p1_text.split("## 第一阶段结论", 1)[-1] if "## 第一阶段结论" in p1_text else p1_text
    p2_conclusion = p2_text.split("## 第二阶段结论", 1)[-1] if "## 第二阶段结论" in p2_text else p2_text
    e01 = _conclusion_pass(p1_conclusion, "E01")
    e02 = _conclusion_pass(p1_conclusion, "E02")
    e03 = _conclusion_pass(p1_conclusion, "E03")
    e04 = _conclusion_pass(p2_conclusion, "E04")
    e05 = _conclusion_pass(p2_conclusion, "E05")

    answers = [
        ("1. 关系是否具有差异性？", "是" if e01 else "否/不足", "E01"),
        ("2. 情绪是否具有连续性？", "是" if e02 else "否/不足", "E02"),
        ("3. 情绪是否具有组合性？", "是" if e03 else "否/不足", "E03"),
        ("4. 自主性是否真实存在于工程机制中？", "是" if e04 else "否/不足", "E04"),
        ("5. 交流是否自然？", "是" if e05 else "否/不足", "E05"),
        ("6. 人格是否真正独立？", "是" if e06_passed else "否/不足", "E06"),
    ]
    lines = [
        "# 针对性实验全阶段总结",
        "",
        f"- 生成时间：{datetime.now(LOCAL_TZ).isoformat(timespec='seconds')}",
        "",
        "## 六问验收",
        "",
    ]
    for question, answer, exp in answers:
        lines.append(f"- {question} **{answer}**（{exp}）")
    lines.extend(
        [
            "",
            "## 阶段结果",
            "",
            f"- 第一阶段：E01={'通过' if e01 else '未通过'}，E02={'通过' if e02 else '未通过'}，E03={'通过' if e03 else '未通过'}",
            f"- 第二阶段：E04={'通过' if e04 else '未通过'}，E05={'通过' if e05 else '未通过'}",
            f"- 第三阶段：E06={'通过' if e06_passed else '未通过'} "
            f"(行为分化均值 {e06_stats.get('avg_action_div', 0):.1f}，"
            f"倾向分化均值 {e06_stats.get('avg_tendency_div', 0):.1f})",
            "",
            "## 后续建议",
            "",
        ]
    )
    if e06_passed and all([e01, e02, e03, e04, e05]):
        lines.append("- 六组核心问题均已得到工程证据支持，可进入下一轮产品化打磨与更长周期观察。")
    else:
        fails = [exp for _, answer, exp in answers if answer != "是"]
        lines.append(f"- 优先回修：{', '.join(fails) if fails else '局部打磨'}。")
        if not e06_passed:
            lines.append("- E06：加强人格数据进入决策/动机的权重，降低统一“比喻+追问” Realization 模板。")
        if not e05:
            lines.append("- E05：继续压缩低信息量输入下的长回复与安慰模板。")
    lines.append("")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_OUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = datetime.now(LOCAL_TZ)
    print(json.dumps({"phase": 3, "started": started.isoformat()}, ensure_ascii=False), flush=True)
    e06 = run_e06()
    conclusions = write_report(e06)
    write_final_summary(bool(conclusions["passed"]), conclusions["stats"])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps({"e06": e06}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "phase": 3,
                "done": True,
                "report": str(OUT),
                "final": str(FINAL_OUT),
                "raw": str(RAW_OUT),
                "e06_passed": conclusions["passed"],
                "elapsed_min": round((datetime.now(LOCAL_TZ) - started).total_seconds() / 60, 1),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
