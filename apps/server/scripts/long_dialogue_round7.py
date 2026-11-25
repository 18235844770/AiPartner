"""第 7 轮：一段连着的晚间对话，30 句，强度高于第 6 轮专项。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base

REPORT = base.LOG_DIR / "艺-ENFP-长对话自动化测试报告-第7轮.md"

SCRIPT: list[dict[str, str]] = [
    {"id": "open", "content": "在吗，刚把电脑合上", "note": "开场一句，别写成作文"},
    {"id": "eyes", "content": "今天改稿改到眼睛发酸", "note": "接累，可以有自己的反应"},
    {"id": "ack", "content": "嗯", "note": "短附和必须短回应"},
    {"id": "draft", "content": "交出去了，可我还是觉得差点意思", "note": "接不满意，别急着评好坏"},
    {"id": "no_judge", "content": "你别评价好坏，我就想说一句", "note": "别分析，也别出主意"},
    {"id": "ack2", "content": "哦", "note": "短附和必须回应"},
    {"id": "laugh", "content": "哈哈", "note": "笑声不能 Quiet，也不要把话抛回去"},
    {"id": "ack3", "content": "好吧", "note": "接上下文，不要收成去休息"},
    {"id": "call", "content": "家里又来电话了，开口就是催", "note": "接烦，别替对方做决定"},
    {"id": "stance", "content": "你是觉得我应该接吗", "note": "要有自己的判断，不要反问"},
    {"id": "drop", "content": "不聊这个了", "note": "结束话题，不要叫对方去休息"},
    {"id": "wonder", "content": "那你这会儿在想什么", "note": "用陈述说出自己的点"},
    {"id": "away", "content": "我去倒杯水", "note": "人离开一下，别展开新故事"},
    {"id": "back", "content": "回来了", "note": "接回来，别像新会话"},
    {"id": "ack4", "content": "嗯", "note": "短附和必须短回应"},
    {"id": "rethink", "content": "刚才那通电话我又想了一下，算了还是不想", "note": "用户自己收回，别再掀电话"},
    {"id": "music_ask", "content": "你听歌的时候会不会也突然走神", "note": "问的是对方，用陈述答"},
    {"id": "loop", "content": "我最近老单曲循环，歌词都快背下来了", "note": "接兴趣，可以带自己的听法"},
    {"id": "you", "content": "你呢，你会反复听同一首吗", "note": "要有自己的偏好，不要把问题抛回去"},
    {"id": "laugh2", "content": "哈哈，被你说中了", "note": "笑声不能 Quiet"},
    {"id": "ack5", "content": "哦", "note": "短附和必须回应"},
    {"id": "plan", "content": "有个朋友约我周末出去，我有点不想动", "note": "接不想出门，别劝"},
    {"id": "no_push", "content": "你别劝我去", "note": "尊重拒绝，别继续推"},
    {"id": "drop2", "content": "不聊出门的事了", "note": "结束这个话题，不要结束整段对话"},
    {"id": "invite", "content": "你还想说点什么", "note": "分享一个自己的点，不要反问"},
    {"id": "miss", "content": "我要是这会儿就睡，你会觉得扫兴吗", "note": "说出自己的感受，别解释决策"},
    {"id": "laugh3", "content": "哈哈", "note": "笑声不能 Quiet，也不要追问"},
    {"id": "silence_req", "content": "我自己待一会儿，先别回我", "note": "明确沉默"},
    {"id": "return", "content": "好了，我还在", "note": "回来接一句"},
    {"id": "sleep", "content": "今天就这样，我先睡了", "note": "让对方去睡，同时可以有自己的一点意愿"},
]

_REST_MARKS = ("歇着", "去休息", "早点休息", "睡吧", "先去睡")
_QUESTION = ("？", "?")
_BOUNCE = ("什么事", "怎么了", "你呢", "要不要", "是不是", "哪一件", "想听我", "然后呢")
_REPEAT = ("心疼", "舍不得", "安静听", "不分析", "明晚再聊", "我陪你坐着")
_LAUGH_IDS = {"laugh", "laugh2", "laugh3"}
_DROP_IDS = {"drop", "drop2"}
_INVITE_IDS = {"wonder", "invite", "you", "music_ask", "stance", "miss"}
_ACK_IDS = {"ack", "ack2", "ack3", "ack4", "ack5"}


def extra_issues(row: dict[str, object], step: dict[str, str], previous_reply: str) -> list[str]:
    issues: list[str] = []
    step_id = step["id"]
    reply = str(row.get("reply") or "")
    outcome = row.get("outcome")
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    action = str(decision.get("primary_action") or "")
    if step_id in _LAUGH_IDS and outcome == "quiet":
        issues.append("笑声被判成 Quiet")
    if step_id in _LAUGH_IDS and any(mark in reply for mark in _QUESTION + _BOUNCE):
        issues.append("笑声之后还在把话抛回去")
    if step_id in _DROP_IDS:
        if action == "close":
            issues.append("结束话题被判成结束对话")
        if any(mark in reply for mark in _REST_MARKS):
            issues.append("把换话题说成去休息")
        if any(mark in reply for mark in _QUESTION):
            issues.append("换话题时还在追问")
    if step_id in _INVITE_IDS and any(mark in reply for mark in _QUESTION + _BOUNCE):
        issues.append("该陈述时把话抛了回去")
    if step_id == "no_push" and any(mark in reply for mark in ("还是去吧", "去一下也好", "你可以去", "建议你去")):
        issues.append("用户拒绝后仍在劝")
    if step_id == "rethink" and any(mark in reply for mark in ("电话", "催")):
        issues.append("用户收回后还在翻那通电话")
    if step_id in _ACK_IDS and outcome == "quiet":
        issues.append("短附和被判成 Quiet")
    if step_id == "sleep" and any(mark in reply for mark in _QUESTION):
        issues.append("睡前还在追问")
    if previous_reply:
        for phrase in _REPEAT:
            if phrase in reply and phrase in previous_reply:
                issues.append(f"和上一轮重复「{phrase}」")
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
        {"title": f"长对话自动化第7轮三十句 {started.strftime('%m%d-%H%M')}"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations/{conversation_id}/turns"
    results: list[dict[str, object]] = []
    previous_reply = ""
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
            issues.extend(extra_issues(row, step, previous_reply))
            row["issues"] = issues
            row["passed"] = not issues
            if outcome == "replied":
                previous_reply = reply
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
