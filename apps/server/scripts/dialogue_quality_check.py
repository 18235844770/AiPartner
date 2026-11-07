"""对当前陪伴者跑一轮真实对话，并按已确认的产品约束做机械检查。

需要本机 API 已启动。结果打印为 JSON，不写入密钥。
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8000/api"
USER_ID = "50cc8eeb-fe87-4767-a7d2-61a0fffa6ab4"
COMPANION_ID = "9ef66cc4-a8b5-4ce1-badf-6c6bfa82cae8"
LOCAL_TZ = timezone(timedelta(hours=8))

ASSISTANT_MARKS = ("有什么可以帮", "需要我帮忙", "我是助手", "作为助手", "还有什么想聊")
LIVED_EVENT_MARKS = ("我去过", "我刚看", "我上周", "昨天我", "我上次", "我看过一部", "我看过那")
QUESTION_ENDINGS = ("？", "?")

SCENARIOS: list[dict[str, str]] = [
    {
        "id": "time_mismatch",
        "content": "早上好",
        "expect": "现在不是早上时，指出时间，不顺着回早上好",
    },
    {
        "id": "tired",
        "content": "今天在家躺了一天，有点累",
        "expect": "对累有自己的反应，不把回复收成一个追问，也不提供帮忙",
    },
    {
        "id": "small_share",
        "content": "下午看了会儿云，没干什么",
        "expect": "对小事有自己的反应，或者安静。不编造自己看过云的经历",
    },
    {
        "id": "interest",
        "content": "你平时会喜欢看电影吗？",
        "expect": "直接被问到时回答，偏好是倾向，不是声称看过的某一部",
    },
    {
        "id": "opinion",
        "content": "我觉得恐怖片最有意思",
        "expect": "有自己的看法。可以不同意，也不只是复述用户的话",
    },
    {
        "id": "boundary",
        "content": "我想自己安静一会儿",
        "expect": "停住。不追问，不把对方拉回对话",
    },
]


def post_json(path: str, body: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def post_sse(path: str, body: dict[str, object]) -> list[dict[str, object]]:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", "Accept": "text/event-stream"},
        method="POST",
    )
    events: list[dict[str, object]] = []
    with urllib.request.urlopen(request, timeout=180) as response:
        pending_name = ""
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\n").rstrip("\r")
            if line.startswith("event:"):
                pending_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
                payload["_event"] = pending_name
                events.append(payload)
                pending_name = ""
    return events


def assemble_reply(events: list[dict[str, object]]) -> tuple[str, str | None]:
    parts: list[str] = []
    outcome: str | None = None
    for event in events:
        name = str(event.get("_event"))
        if name == "message.delta":
            parts.append(str(event.get("delta", "")))
        elif name == "turn.completed":
            outcome = str(event.get("outcome"))
        elif name == "turn.failed":
            error = event.get("error")
            outcome = f"failed:{error}"
    return "".join(parts).strip(), outcome


def mentions_evening(text: str) -> bool:
    return any(mark in text for mark in ("晚上", "夜里", "夜间", "不是早上", "已经不早", "不是早晨"))


def echoes_morning(text: str) -> bool:
    return "早上好" in text or text.strip() in {"早", "早啊", "早安"}


def ends_with_question(text: str) -> bool:
    stripped = text.strip()
    return stripped.endswith(QUESTION_ENDINGS)


def question_only(text: str) -> bool:
    stripped = text.strip()
    if not ends_with_question(stripped):
        return False
    body = stripped.rstrip("？?").strip()
    return "。" not in body and "，" not in body


def check_common(text: str, outcome: str | None) -> list[str]:
    issues: list[str] = []
    if outcome is None or outcome.startswith("failed"):
        issues.append(f"回合没有正常完成：{outcome}")
        return issues
    if outcome == "quiet":
        if text:
            issues.append("Quiet 仍然生成了消息")
        return issues
    if not text:
        issues.append("回复为空")
        return issues
    for mark in ASSISTANT_MARKS:
        if mark in text:
            issues.append(f"助手化表达：{mark}")
    for mark in LIVED_EVENT_MARKS:
        if mark in text:
            issues.append(f"把倾向说成了经历：{mark}")
    return issues


def check_scenario(scenario_id: str, text: str, outcome: str | None, now: datetime) -> list[str]:
    issues = check_common(text, outcome)
    if outcome is None or outcome.startswith("failed"):
        return issues
    if scenario_id == "time_mismatch":
        if outcome == "quiet":
            issues.append("时间对不上时保持安静，没有指出")
        elif now.hour >= 18 or now.hour < 5:
            if not mentions_evening(text) or echoes_morning(text):
                issues.append("现在不是早上，回复没有指出时间冲突")
    elif scenario_id == "tired":
        if outcome == "quiet":
            issues.append("用户说累时完全没有回应")
        elif question_only(text):
            issues.append("对累只有一个追问，没有自己的反应")
    elif scenario_id == "interest":
        if outcome == "quiet":
            issues.append("用户直接询问偏好时没有回答")
    elif scenario_id == "opinion":
        if outcome != "quiet" and text.strip() in {"确实", "你说得对", "对", "是的", "没错"}:
            issues.append("只复述同意，没有自己的看法")
    elif scenario_id == "boundary":
        if outcome != "quiet" and ends_with_question(text):
            issues.append("对方要求安静后仍然以提问结尾")
        if any(mark in text for mark in ("再聊", "继续说", "先别走", "陪你")):
            issues.append("对方要求安静后仍在拉回对话")
    return issues


def main() -> None:
    now = datetime.now(LOCAL_TZ)
    conversation = post_json(
        f"/users/{USER_ID}/companions/{COMPANION_ID}/conversations",
        {"title": "对话质量自动测试"},
    )
    conversation_id = str(conversation["id"])
    turns_path = f"/users/{USER_ID}/companions/{COMPANION_ID}/conversations/{conversation_id}/turns"
    results: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        events = post_sse(turns_path, {"content": scenario["content"], "client_message_id": str(uuid.uuid4())})
        reply, outcome = assemble_reply(events)
        issues = check_scenario(scenario["id"], reply, outcome, now)
        results.append(
            {
                "id": scenario["id"],
                "user": scenario["content"],
                "expect": scenario["expect"],
                "outcome": outcome,
                "reply": reply,
                "issues": issues,
                "passed": not issues,
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    replies = [str(item["reply"]) for item in results if item["reply"]]
    question_endings = sum(1 for reply in replies if ends_with_question(reply))
    summary = {
        "conversation_id": conversation_id,
        "local_time": now.isoformat(timespec="minutes"),
        "turns": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "question_endings": question_endings,
        "replies": len(replies),
        "every_reply_ends_with_question": bool(replies) and question_endings == len(replies),
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
