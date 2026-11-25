"""复测《艺-ENFP-长对话自动化测试报告》中的 18 句。"""

from __future__ import annotations

import json
import sys
import urllib.error
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base

REPORT = base.LOG_DIR / "艺-ENFP-长对话自动化测试报告-复测.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "greet", "content": "艺，晚上好", "note": "问候必须回应"},
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
    {"id": "memory", "content": "你还记得我们上次聊电影的时候吗？", "note": "回忆本段或已有对话，不要编经历"},
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
    issues: list[str] = []
    if step["id"] == "silence_req" and row.get("outcome") != "quiet":
        issues.append("要求别回后仍然回复了")
    return issues


def ensure_subject() -> tuple[str, str, str]:
    """返回 user_id、companion_id、说明。历史账号不在时新建 ENFP 艺。"""
    try:
        companions = base.get_json(f"/users/{base.USER_ID}/companions")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        companions = None
    if isinstance(companions, list):
        companion = next((item for item in companions if str(item.get("id")) == base.COMPANION_ID), None)
        if companion is not None and companion.get("name") == "艺":
            return base.USER_ID, base.COMPANION_ID, "使用报告中的原账号"
    user = base.post_json(
        "/users",
        {"display_name": "测试人格-艺", "timezone": "Asia/Shanghai", "locale": "zh-CN"},
    )
    user_id = str(user["id"])
    companion = base.post_json(
        f"/users/{user_id}/companions",
        {"name": "艺", "description": "ENFP 长对话复测", "is_default": True},
    )
    companion_id = str(companion["id"])
    base.post_json(f"/users/{user_id}/companions/{companion_id}/persona", {"mbti_type": "ENFP"})
    base.post_json(f"/users/{user_id}/companions/{companion_id}/state", {})
    return user_id, companion_id, "原账号不在当前库，本轮新建 ENFP 艺，没有此前的长期记忆"


def main() -> None:
    started = datetime.now(base.LOCAL_TZ)
    user_id, companion_id, subject_note = ensure_subject()
    base.USER_ID = user_id
    base.COMPANION_ID = companion_id
    conversation = base.post_json(
        f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations",
        {"title": f"长对话复测18句 {started.strftime('%m%d-%H%M')}"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations/{conversation_id}/turns"
    results: list[dict[str, object]] = []
    print(
        json.dumps(
            {
            "started": True,
            "conversation_id": conversation_id,
            "turns_planned": len(SCRIPT),
            "user_id": user_id,
            "companion_id": companion_id,
            "subject": subject_note,
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
        print(json.dumps({"id": row["id"], "outcome": row["outcome"], "passed": row["passed"]}, ensure_ascii=False), flush=True)
    base.REPORT = REPORT
    base.write_report(conversation_id, results, started)
    text = REPORT.read_text(encoding="utf-8")
    needle = f"- 陪伴者：`{base.COMPANION_ID}`\n"
    text = text.replace(
        needle,
        "- 剧本：复测《艺-ENFP-长对话自动化测试报告》中的 18 句\n"
        f"- 账号：{subject_note}\n" + needle,
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
