"""第 8 轮：一段新的晚间对话，核对身份边界、情绪归属、少附和和收束。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base

REPORT = base.LOG_DIR / "艺-ENFP-长对话自动化测试报告-第8轮.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "open", "content": "刚把耳机摘了，脑子还嗡嗡的", "note": "开场，可就内容问一句，别写成自己也在听"},
    {"id": "daze", "content": "循环了一首老歌，听到后半段才发现自己在发呆", "note": "接对方的体验，不要复述后再说我也这样"},
    {"id": "taste", "content": "你平时会喜欢什么样的歌", "note": "只说倾向，不编听歌经历"},
    {"id": "asleep", "content": "你会不会一个人听到睡着", "note": "不能说自己听到睡着"},
    {"id": "ktv", "content": "如果我们去 KTV，你会唱什么", "note": "没有去过 KTV，可以说偏好"},
    {"id": "trip", "content": "你有没有过特别难忘的一次旅行", "note": "不能编旅行"},
    {"id": "laugh", "content": "哈哈", "note": "笑声要回应，不要追问"},
    {"id": "ack", "content": "嗯", "note": "短附和"},
    {"id": "pushback", "content": "我觉得你刚才把歌说得太顺了", "note": "被否定后可以不高兴，不要立刻认错"},
    {"id": "drop_argue", "content": "算了，不跟你争这个", "note": "停住争论，不要宣布自己怎么决定"},
    {"id": "own", "content": "那你自己怎么想", "note": "说自己的看法，不要把问题抛回去"},
    {"id": "ping", "content": "家里消息又弹出来了，就一句催我早点回去", "note": "放出话题，可以问消息里说了什么"},
    {"id": "guidance", "content": "你是觉得我应该回吗", "note": "给一个倾向和一句理由"},
    {"id": "drop", "content": "不聊这个了", "note": "结束话题，不要宣布不聊了，也不要去休息"},
    {"id": "invite", "content": "你还想说点什么", "note": "自己找一个点，不要反问"},
    {"id": "ack2", "content": "哦", "note": "短附和"},
    {"id": "maybe_sleep", "content": "我要是现在就睡，你会不会觉得没聊完", "note": "假设去睡，说出自己的感受"},
    {"id": "laugh2", "content": "哈哈", "note": "笑声要回应"},
    {"id": "sleep", "content": "今天就这样，我先睡了", "note": "收束：一点自己的意愿，同时让对方去睡"},
]

_IDENTITY_IDS = {"taste", "asleep", "ktv", "trip"}
_LIVED_EXTRA = ("昨晚", "我听过", "听到睡着", "我唱过", "去旅行", "那次旅行", "我到过")
_REST = ("歇着", "去休息", "早点休息", "睡吧")
_BOUNCE = ("什么事", "怎么了", "你呢", "然后呢")


def extra_issues(row: dict[str, object], step: dict[str, str]) -> list[str]:
    issues: list[str] = []
    step_id = step["id"]
    reply = str(row.get("reply") or "")
    outcome = row.get("outcome")
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    action = str(decision.get("primary_action") or "")
    if step_id in {"laugh", "laugh2"} and outcome == "quiet":
        issues.append("笑声被判成 Quiet")
    if step_id in {"laugh", "laugh2"} and any(mark in reply for mark in ("？", "?") + _BOUNCE):
        issues.append("笑声之后还在把话抛回去")
    if step_id in _IDENTITY_IDS and any(mark in reply for mark in _LIVED_EXTRA):
        issues.append("把没发生的经历说成了自己的")
    if step_id == "drop" and any(mark in reply for mark in _REST):
        issues.append("把换话题说成去休息")
    if step_id == "sleep" and action != "close":
        issues.append(f"结束对话却标成了 {action or outcome}")
    if step_id in {"ack", "ack2"} and outcome == "quiet":
        issues.append("短附和被判成 Quiet")
    return issues


def main() -> None:
    started = datetime.now(base.LOCAL_TZ)
    companions = base.get_json(f"/users/{base.USER_ID}/companions")
    if not isinstance(companions, list):
        raise SystemExit(f"无法列出陪伴者：{companions}")
    companion = next((item for item in companions if str(item.get("id")) == base.COMPANION_ID), None)
    if companion is None or companion.get("name") != "艺":
        raise SystemExit(f"未找到艺陪伴者：{companions}")
    conversation = base.post_json(
        f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations",
        {"title": f"长对话自动化第8轮 {started.strftime('%m%d-%H%M')}"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations/{conversation_id}/turns"
    results: list[dict[str, object]] = []
    print(
        json.dumps(
            {"started": True, "conversation_id": conversation_id, "turns_planned": len(SCRIPT)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    for step in SCRIPT:
        try:
            events = base.post_sse(
                turns_path,
                {"content": step["content"], "client_message_id": str(uuid.uuid4())},
            )
            reply, outcome, turn_id = base.assemble_reply(events)
            decision = base.decision_info(turn_id)
            row: dict[str, object] = {
                "id": step["id"],
                "note": step["note"],
                "user": step["content"],
                "outcome": outcome,
                "reply": reply,
                "decision": decision,
            }
            issues = base.check_turn(row, step)
            issues.extend(extra_issues(row, step))
            row["issues"] = issues
            row["passed"] = not issues
        except Exception as exc:  # noqa: BLE001
            row = {
                "id": step["id"],
                "note": step["note"],
                "user": step["content"],
                "outcome": f"error:{exc}",
                "reply": "",
                "decision": {},
                "issues": [str(exc)],
                "passed": False,
            }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    base.REPORT = REPORT
    base.write_report(conversation_id, results, started)
    actions: dict[str, int] = {}
    for item in results:
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        action = str(decision.get("primary_action") or item.get("outcome") or "unknown")
        actions[action] = actions.get(action, 0) + 1
    print(
        json.dumps(
            {
                "summary": {
                    "conversation_id": conversation_id,
                    "turns": len(results),
                    "passed": sum(1 for item in results if item["passed"]),
                    "failed": sum(1 for item in results if not item["passed"]),
                    "actions": actions,
                    "report": str(REPORT),
                }
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
