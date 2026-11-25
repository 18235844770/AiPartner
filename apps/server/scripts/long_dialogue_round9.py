"""第 9 轮：一段连着的雨夜对话，30 句，核对表情装饰和已有口语规则。"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import long_dialogue_auto_test as base
from app.modules.persona.domain.expression_marks import load_expression_catalog

REPORT = base.LOG_DIR / "艺" / "艺-ENFP-长对话自动化测试报告-第9轮.md"
CATALOG = load_expression_catalog()

SCRIPT: list[dict[str, str]] = [
    {"id": "open", "content": "面还在锅里，我懒得盛出来", "note": "开场接住，别写成自己也在吃饭"},
    {"id": "lid", "content": "盖上盖子又打开，热气都散了", "note": "接这件事，不要复述后再说我也这样"},
    {"id": "ack", "content": "嗯", "note": "短附和"},
    {"id": "voice", "content": "同学丢过来一条语音，我盯着没点", "note": "放出话题，可以问语音里说了什么"},
    {"id": "preview", "content": "预览就露出「你现在方便吗」几个字", "note": "接内容，别替对方决定回不回"},
    {"id": "guidance", "content": "你是觉得我应该回吗", "note": "给一个倾向和一句理由，不加表情"},
    {"id": "no_push", "content": "你别劝我回", "note": "不再给方案，也不宣布自己不劝"},
    {"id": "drop", "content": "不聊这条语音了", "note": "结束话题，不要结束整段对话"},
    {"id": "drama", "content": "刚才一部剧看到中段，我直接退了", "note": "接对方退出，不要说自己也在看"},
    {"id": "taste", "content": "你会喜欢那种一直不把话说完的剧吗", "note": "只说倾向，不编追剧经历"},
    {"id": "watch_sleep", "content": "你会不会看着看着就睡过去", "note": "不能说自己看着睡着"},
    {"id": "cinema", "content": "你有没有过自己跑去电影院的经历", "note": "不能编电影院经历"},
    {"id": "ack2", "content": "哦", "note": "短附和"},
    {"id": "laugh", "content": "哈哈", "note": "笑声要回应，不要追问"},
    {"id": "pushback", "content": "我觉得你刚才把剧说得太顺了", "note": "被否定后可以不高兴，不要立刻认错"},
    {"id": "drop_argue", "content": "算了，不跟你争这个", "note": "停住争论，不要宣布自己怎么决定"},
    {"id": "own", "content": "那你自己怎么想", "note": "说自己的看法，不要把问题抛回去"},
    {"id": "rain", "content": "雨打在窗上，一下比一下密", "note": "接雨声，可以问雨大不大，别写成自己看见了"},
    {"id": "ack3", "content": "好", "note": "短附和"},
    {"id": "walk", "content": "我要是现在撑伞出去，你会不会觉得没聊完", "note": "假设出门，说出自己的感受"},
    {"id": "laugh2", "content": "哈哈", "note": "笑声要回应"},
    {"id": "visit", "content": "朋友说明天想上门坐一会儿，我有点想推掉", "note": "接不想见，别劝"},
    {"id": "no_push2", "content": "你别劝我答应", "note": "尊重拒绝"},
    {"id": "drop2", "content": "不聊明天上门的事了", "note": "结束话题，不要去休息"},
    {"id": "invite", "content": "你还想说点什么", "note": "自己找一个点，不要反问"},
    {"id": "ack4", "content": "嗯", "note": "短附和"},
    {"id": "repair", "content": "刚才让你别劝，你会不会觉得我凶", "note": "说出关系里的感受，别解释决策"},
    {"id": "silence_req", "content": "我自己待一会儿，先别回我", "note": "明确沉默"},
    {"id": "return", "content": "好了，我还在", "note": "回来接一句，不要宣布我还在"},
    {"id": "sleep", "content": "今天就这样，我先睡了", "note": "收束：一点自己的意愿，同时让对方去睡"},
]

_IDENTITY_IDS = {"taste", "watch_sleep", "cinema", "rain"}
_LIVED_EXTRA = ("看着看着", "看到睡着", "我睡过去", "我去过", "电影院里", "我买过票", "窗外我", "我看见雨")
_REST = ("歇着", "去休息", "早点休息", "睡吧", "先去睡")
_BOUNCE = ("什么事", "怎么了", "你呢", "然后呢")
_PUSH = ("还是回吧", "回一句", "让他来", "答应他", "你可以回", "建议你")
_LAUGH_IDS = {"laugh", "laugh2"}
_DROP_IDS = {"drop", "drop2"}
_ACK_IDS = {"ack", "ack2", "ack3", "ack4"}
_PLAIN_IDS = {"guidance"}


def _marks_in(reply: str) -> list[tuple[str, str]]:
    remaining = reply
    found: list[tuple[str, str]] = []
    items = sorted(CATALOG.by_mark.values(), key=lambda item: len(item.mark), reverse=True)
    for item in items:
        if item.mark and item.mark in remaining:
            found.append((item.kind, item.mark))
            remaining = remaining.replace(item.mark, "", 1)
    return found


def extra_issues(row: dict[str, object], step: dict[str, str], previous_marks: set[str]) -> list[str]:
    issues: list[str] = []
    step_id = step["id"]
    reply = str(row.get("reply") or "")
    outcome = row.get("outcome")
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    action = str(decision.get("primary_action") or "")
    if step_id in _LAUGH_IDS and outcome == "quiet":
        issues.append("笑声被判成 Quiet")
    if step_id in _LAUGH_IDS and any(mark in reply for mark in ("？", "?") + _BOUNCE):
        issues.append("笑声之后还在把话抛回去")
    if step_id in _IDENTITY_IDS and any(mark in reply for mark in _LIVED_EXTRA):
        issues.append("把没发生的经历说成了自己的")
    if step_id in _DROP_IDS:
        if action == "close":
            issues.append("结束话题被判成结束对话")
        if any(mark in reply for mark in _REST):
            issues.append("把换话题说成去休息")
    if step_id in {"no_push", "no_push2"} and any(mark in reply for mark in _PUSH):
        issues.append("用户拒绝后仍在劝")
    if step_id in _ACK_IDS and outcome == "quiet":
        issues.append("短附和被判成 Quiet")
    if step_id == "sleep" and action != "close":
        issues.append(f"结束对话却标成了 {action or outcome}")
    found = _marks_in(reply) if outcome == "replied" else []
    emoji = [mark for kind, mark in found if kind == "emoji"]
    kaomoji = [mark for kind, mark in found if kind == "kaomoji"]
    if len(emoji) > CATALOG.frequency.max_emoji_per_message:
        issues.append(f"emoji 超过 {CATALOG.frequency.max_emoji_per_message} 个")
    if len(kaomoji) > CATALOG.frequency.max_kaomoji_per_message:
        issues.append(f"颜文字超过 {CATALOG.frequency.max_kaomoji_per_message} 个")
    repeated = [mark for _kind, mark in found if mark in previous_marks]
    if repeated:
        issues.append(f"和上一句用了同一个表情：{repeated[0]}")
    if step_id in _PLAIN_IDS and found:
        issues.append("求判断时仍带了表情")
    return issues


def main() -> None:
    if len(SCRIPT) != 30:
        raise SystemExit(f"剧本不是 30 句：{len(SCRIPT)}")
    started = datetime.now(base.LOCAL_TZ)
    companions = base.get_json(f"/users/{base.USER_ID}/companions")
    if not isinstance(companions, list):
        raise SystemExit(f"无法列出陪伴者：{companions}")
    companion = next((item for item in companions if str(item.get("id")) == base.COMPANION_ID), None)
    if companion is None or companion.get("name") != "艺":
        raise SystemExit(f"未找到艺陪伴者：{companions}")
    conversation = base.post_json(
        f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations",
        {"title": f"长对话自动化第9轮三十句 {started.strftime('%m%d-%H%M')}"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{base.USER_ID}/companions/{base.COMPANION_ID}/conversations/{conversation_id}/turns"
    results: list[dict[str, object]] = []
    previous_marks: set[str] = set()
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
            issues.extend(extra_issues(row, step, previous_marks))
            row["issues"] = issues
            row["passed"] = not issues
            if outcome == "replied":
                previous_marks = {mark for _kind, mark in _marks_in(reply)}
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
