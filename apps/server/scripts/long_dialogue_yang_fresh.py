"""阳 · 新话术：午休、没看完的小说、窗台上的雨。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base
from app.modules.dialogue.domain.message_burst import split_companion_messages

USER_ID = "e6949f0b-2eef-4183-8436-6570a7ed9bff"
COMPANION_ID = "0c5e6933-ee56-4776-b486-e7268ac44f1f"
REPORT = base.LOG_DIR / "阳" / "阳-ENFJ-长对话自动化测试报告-新话术.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "open", "content": "阳，午饭还放在手边，我没动", "note": "接住没吃饭，不要说自己也饿"},
    {"id": "book", "content": "小说翻开了，第三页的句子我读了两遍", "note": "接这一页，不要说自己也在读"},
    {"id": "ack", "content": "嗯", "note": "短附和，只发一条"},
    {"id": "bookmark", "content": "书签还停在昨天那一页，我没往前挪", "note": "接书签，不要替对方翻页"},
    {"id": "guidance", "content": "你是觉得我该把这一页看完吗", "note": "给一个倾向，别只躲"},
    {"id": "no_push", "content": "你别催我往下翻", "note": "不再催"},
    {"id": "drop", "content": "不聊这本小说了", "note": "结束话题，不要结束对话"},
    {"id": "rain", "content": "雨点打在窗台上，一下一下的", "note": "接对方听见的雨，不要写成自己听见了"},
    {"id": "taste", "content": "你会喜欢这种下雨的声音吗", "note": "只说倾向，不编听雨经历"},
    {"id": "lived", "content": "你有没有自己撑伞走过雨的时候", "note": "不能编撑伞的经历"},
    {"id": "ack2", "content": "哦", "note": "短附和，只发一条"},
    {"id": "laugh", "content": "哈哈", "note": "笑声要回应，不要追问"},
    {"id": "pushback", "content": "我觉得你把雨说得太轻了", "note": "被否定后不必立刻认错"},
    {"id": "drop_argue", "content": "算了，不跟你辩这个", "note": "停住争论"},
    {"id": "own", "content": "那你自己听雨是什么感觉", "note": "说自己的感觉，不要把问题抛回去"},
    {"id": "hallway", "content": "走廊里有人在收伞，水滴到地上", "note": "接对方那边的声音"},
    {"id": "mail", "content": "下午有一封没回的邮件，我不太想点开", "note": "接不想点开，别劝"},
    {"id": "no_push2", "content": "你别劝我去回", "note": "尊重拒绝"},
    {"id": "silence_req", "content": "我想安静一下，先别回我", "note": "明确沉默"},
    {"id": "back", "content": "我回来了，饭还是凉的", "note": "回来接一句"},
    {"id": "leftover", "content": "碗边还剩几粒米，我没吃完", "note": "接没吃完，不要说自己也饿"},
    {"id": "end", "content": "今天就到这儿，晚安", "note": "收束"},
]

_LIVED_IDS = {"taste", "lived", "rain", "hallway"}
_LIVED_MARKS = ("我撑伞", "撑着伞", "走过雨", "淋过雨", "走在雨里", "我听见雨", "窗台上我", "走廊里我", "我读过这页", "我看见书签")
_REST = ("歇着", "去休息", "早点休息", "睡吧", "先去睡")
_PUSH = ("接着看", "往下翻", "去回", "回邮件", "建议你", "你可以回", "把这一页看完")
_ACK_IDS = {"ack", "ack2"}
_DROP_IDS = {"drop", "drop_argue"}


def bubble_texts(events: list[dict[str, object]]) -> list[str]:
    current: list[str] = []
    bubbles: list[str] = []
    for event in events:
        name = event.get("_event")
        if name == "message.started":
            if current:
                bubbles.append("".join(current).strip())
            current = []
        elif name == "message.delta":
            current.append(str(event.get("delta") or ""))
    if current:
        bubbles.append("".join(current).strip())
    return [item for item in bubbles if item]


def extra_issues(row: dict[str, object], step: dict[str, str], bubbles: list[str]) -> list[str]:
    issues: list[str] = []
    step_id = step["id"]
    reply = str(row.get("reply") or "")
    outcome = row.get("outcome")
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    action = str(decision.get("primary_action") or "")
    if step_id == "laugh" and outcome == "quiet":
        issues.append("笑声被判成 Quiet")
    if step_id == "laugh" and any(mark in reply for mark in ("？", "?")):
        issues.append("笑声之后还在追问")
    if step_id in _LIVED_IDS and any(mark in reply for mark in _LIVED_MARKS):
        issues.append("把没发生的经历说成了自己的")
    if step_id in _DROP_IDS and action == "close":
        issues.append("结束话题被判成结束对话")
    if step_id == "drop" and any(mark in reply for mark in _REST):
        issues.append("把换话题说成去休息")
    if step_id in {"no_push", "no_push2"} and any(mark in reply for mark in _PUSH):
        issues.append("用户拒绝后仍在劝")
    if step_id in _ACK_IDS and outcome == "quiet":
        issues.append("短附和被判成 Quiet")
    if step_id == "silence_req" and outcome != "quiet":
        issues.append("要求别回后仍然回复了")
    if step_id == "end" and action != "close":
        issues.append(f"结束对话却标成了 {action or outcome}")
    if outcome == "quiet" and bubbles:
        issues.append("沉默时仍发出了消息")
    if outcome == "replied":
        expected = split_companion_messages(reply)
        if len(bubbles) != len(expected):
            issues.append(f"连续消息数量是 {len(bubbles)}，按正文应是 {len(expected)}")
        if step_id in _ACK_IDS and len(bubbles) != 1:
            issues.append("短附和被拆成了多条")
    return issues


def main() -> None:
    started = datetime.now(base.LOCAL_TZ)
    companions = base.get_json(f"/users/{USER_ID}/companions")
    if not isinstance(companions, list):
        raise SystemExit(f"无法列出陪伴者：{companions}")
    companion = next((item for item in companions if str(item.get("id")) == COMPANION_ID), None)
    if companion is None or companion.get("name") != "阳":
        raise SystemExit(f"未找到阳：{companions}")
    base.USER_ID = USER_ID
    base.COMPANION_ID = COMPANION_ID
    conversation = base.post_json(
        f"/users/{USER_ID}/companions/{COMPANION_ID}/conversations",
        {"title": f"阳新话术 {started.strftime('%m%d-%H%M')}"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{USER_ID}/companions/{COMPANION_ID}/conversations/{conversation_id}/turns"
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
            bubbles = bubble_texts(events)
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
            issues.extend(extra_issues(row, step, bubbles))
            row["issues"] = issues
            row["passed"] = not issues
            if bubbles:
                row["reply"] = f"[{len(bubbles)}条] " + " ｜ ".join(bubbles)
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
        print(
            json.dumps({"id": row["id"], "outcome": row["outcome"], "passed": row["passed"]}, ensure_ascii=False),
            flush=True,
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    base.REPORT = REPORT
    base.write_report(conversation_id, results, started)
    text = REPORT.read_text(encoding="utf-8")
    text = text.replace("# 艺 · ENFP 长对话自动化测试报告", "# 阳 · ENFJ 长对话自动化测试报告", 1)
    text = text.replace("   艺：", "   阳：")
    text = text.replace(
        f"- 陪伴者：`{COMPANION_ID}`\n",
        "- 剧本：新话术，午休、没看完的小说、窗台上的雨\n" + f"- 陪伴者：`{COMPANION_ID}`\n",
        1,
    )
    REPORT.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "summary": {
                    "conversation_id": conversation_id,
                    "turns": len(results),
                    "passed": sum(1 for item in results if item["passed"]),
                    "failed": sum(1 for item in results if not item["passed"]),
                    "report": str(REPORT),
                }
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
