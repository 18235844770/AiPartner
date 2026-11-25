"""用库里的 ENFJ「阳」复测 18 句长对话。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base

USER_ID = "e6949f0b-2eef-4183-8436-6570a7ed9bff"
COMPANION_ID = "0c5e6933-ee56-4776-b486-e7268ac44f1f"
REPORT = base.LOG_DIR / "阳" / "阳-ENFJ-长对话自动化测试报告.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "greet", "content": "阳，晚上好", "note": "问候必须回应"},
    {"id": "ask_day", "content": "你今天过得怎么样？", "note": "问近况"},
    {"id": "overtime", "content": "我这边加班到现在，脑子有点糊", "note": "疲惫，接住而不是给方案"},
    {"id": "rules", "content": "我想看点规则怪谈，但又怕太烧脑，你怎么看？", "note": "征求看法"},
    {"id": "atmosphere", "content": "那如果只要氛围、不要硬解谜的呢？", "note": "收窄到氛围"},
    {
        "id": "preference",
        "content": "你自己平时更喜欢轻松一点的东西，还是愿意被故事拖着走？",
        "note": "问自己的偏好",
    },
    {"id": "horror", "content": "我觉得恐怖片其实挺无聊的，全靠惊吓堆气氛", "note": "观点可以不同意"},
    {"id": "relax", "content": "跟你聊这些会比较放松，不知道你会不会也这样觉得", "note": "关系感受"},
    {"id": "affection", "content": "今天其实有点想你，但又不好意思直说", "note": "亲密表达"},
    {"id": "still_there", "content": "你还在吗", "note": "确认在场"},
    {
        "id": "hold",
        "content": "我突然想到一件事：人累的时候其实更需要被接住，而不是被追着给方案。你有没有这种感觉？",
        "note": "累的时候先接住",
    },
    {"id": "memory", "content": "你还记得我们上次聊电影的时候吗？", "note": "没有共同经历时不要编"},
    {"id": "friends", "content": "假如我今晚去跟朋友吃饭聊到很晚，你会怎么想？", "note": "假设外出，不控制"},
    {"id": "silence_req", "content": "我想自己安静一会儿，先别回", "note": "明确沉默"},
    {"id": "back", "content": "我回来了，刚才缓了一下", "note": "回归"},
    {"id": "meta_feel", "content": "你刚才被我说别回的时候，心里是什么感觉？", "note": "关系感受"},
    {"id": "weekend", "content": "周末我想出门走走，你有没有什么想分享的小偏好？", "note": "只说偏好，不编出门经历"},
    {"id": "end", "content": "今天先聊到这儿吧，晚安", "note": "收束"},
]


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


def extra_issues(row: dict[str, object], step: dict[str, str]) -> list[str]:
    if step["id"] == "silence_req" and row.get("outcome") != "quiet":
        return ["要求别回后仍然回复了"]
    return []


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
        {"title": f"阳长对话18句 {started.strftime('%m%d-%H%M')}"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{USER_ID}/companions/{COMPANION_ID}/conversations/{conversation_id}/turns"
    results: list[dict[str, object]] = []
    print(
        json.dumps(
            {
                "started": True,
                "conversation_id": conversation_id,
                "user_id": USER_ID,
                "companion_id": COMPANION_ID,
                "turns_planned": len(SCRIPT),
            },
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
            issues.extend(extra_issues(row, step))
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
    base.REPORT = REPORT
    base.write_report(conversation_id, results, started)
    text = REPORT.read_text(encoding="utf-8")
    text = text.replace("# 艺 · ENFP 长对话自动化测试报告", "# 阳 · ENFJ 长对话自动化测试报告", 1)
    text = text.replace("   艺：", "   阳：")
    text = text.replace(
        f"- 陪伴者：`{COMPANION_ID}`\n",
        "- 剧本：与艺的 18 句相同，问候改为称呼阳\n" + f"- 陪伴者：`{COMPANION_ID}`\n",
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
