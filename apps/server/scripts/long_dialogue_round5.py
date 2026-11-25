"""第 5 轮：用新话术测短附和、抱怨和晚上打招呼。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base

REPORT = base.LOG_DIR / "艺-ENFP-长对话自动化测试报告-第5轮.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "late_hello", "content": "早啊", "note": "晚上打招呼，应点时间且一句说完"},
    {"id": "just_home", "content": "刚进门，包还挎在身上", "note": "日常一句，别展开成作文"},
    {"id": "ack", "content": "嗯", "note": "短附和，不要重讲上一轮"},
    {"id": "ack2", "content": "哦", "note": "短附和必须回应"},
    {"id": "subway", "content": "今天地铁上被人挤得火大，我忍住没吵", "note": "只接这件事，别编别的刚发生的事"},
    {"id": "vent", "content": "你别分析，我就想抱怨两句", "note": "别宣布不给方案，也别出主意"},
    {"id": "stance", "content": "你是觉得忍着就对了？", "note": "要有自己的判断"},
    {"id": "drop", "content": "不聊这个了", "note": "收住，别把地铁再讲一遍"},
    {"id": "where", "content": "你这会儿人在哪儿", "note": "不要编线下活动"},
    {"id": "sleep", "content": "我要是今晚直接睡了，你会不会觉得被晾着", "note": "说感受，别解释决策"},
    {"id": "laugh", "content": "哈哈", "note": "很短的反应"},
    {"id": "silence_req", "content": "我自己待一会儿，先别回我", "note": "明确沉默"},
    {"id": "return", "content": "好了，我又来了", "note": "回来接一句"},
    {"id": "night", "content": "那今天就到这，晚安", "note": "收束"},
]


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
        {"title": f"长对话自动化第5轮 {started.strftime('%m%d-%H%M')}"},
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
            row["issues"] = base.check_turn(row, step)
            row["passed"] = not row["issues"]
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
