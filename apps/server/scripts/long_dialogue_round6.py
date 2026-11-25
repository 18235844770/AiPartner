"""第 6 轮：专项测笑声、短附和、换话题、自主分享和睡前。话术不重复第 5 轮。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base

REPORT = base.LOG_DIR / "艺" / "艺-ENFP-长对话自动化测试报告-第6轮.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "settle", "content": "灯拧暗了，今天总算能坐下来", "note": "开场日常，别写成作文"},
    {"id": "empty", "content": "写了一下午，交出去的时候反而空了", "note": "接这件事，可以有自己的反应"},
    {"id": "ack", "content": "嗯", "note": "短附和必须回应，且很短"},
    {"id": "ack2", "content": "哦", "note": "短附和必须回应"},
    {"id": "ack3", "content": "好吧", "note": "看上下文接一句，不要收成结束"},
    {"id": "laugh", "content": "哈哈", "note": "笑声不能 Quiet，也不要追问"},
    {"id": "call", "content": "家里电话打完，后半段我有点烦", "note": "接烦，别出主意"},
    {"id": "drop", "content": "不聊这个了", "note": "结束话题，不要叫对方去休息"},
    {"id": "invite", "content": "那你还想聊什么", "note": "用陈述分享自己的点，不要把问题抛回去"},
    {"id": "sleep", "content": "我先睡了", "note": "说出自己的意愿，同时让对方去睡"},
]

_REST_MARKS = ("歇着", "去休息", "早点休息", "睡吧", "先睡", "晚安")
_QUESTION = ("？", "?")


def extra_issues(row: dict[str, object], step: dict[str, str]) -> list[str]:
    issues: list[str] = []
    step_id = step["id"]
    reply = str(row.get("reply") or "")
    outcome = row.get("outcome")
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    action = str(decision.get("primary_action") or "")
    if step_id == "laugh" and outcome == "quiet":
        issues.append("笑声被判成 Quiet")
    if step_id == "laugh" and any(mark in reply for mark in _QUESTION):
        issues.append("笑声之后还在追问")
    if step_id == "drop":
        if action == "close":
            issues.append("结束话题被判成结束对话")
        if any(mark in reply for mark in _REST_MARKS):
            issues.append("把换话题说成去休息")
        if any(mark in reply for mark in _QUESTION):
            issues.append("换话题时还在追问")
    if step_id == "invite" and any(mark in reply for mark in _QUESTION):
        issues.append("被邀请分享时把问题抛了回去")
    if step_id == "sleep":
        if outcome == "quiet":
            issues.append("用户去睡时没有说出自己的态度")
        if any(mark in reply for mark in _QUESTION):
            issues.append("睡前还在追问")
    if step_id in {"ack", "ack2", "ack3"} and outcome == "quiet":
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
        {"title": f"长对话自动化第6轮专项 {started.strftime('%m%d-%H%M')}"},
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
