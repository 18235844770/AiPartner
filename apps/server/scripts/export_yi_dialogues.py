"""把名叫艺的陪伴者的会话和决策导出成 Markdown。"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SQL = Path(__file__).with_suffix(".sql")
OUT = ROOT / "艺-全部对话与决策记录.md"
LOCAL = timezone(timedelta(hours=8))
SENDER = {"user": "用户", "companion": "艺", "system": "系统"}


def load() -> list[dict[str, object]]:
    completed = subprocess.run(
        ["docker", "exec", "-i", "docker-postgres-1", "psql", "-U", "companion", "-d", "companion", "-t", "-A"],
        input=SQL.read_text(encoding="utf-8"),
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def local_time(value: str | None) -> str:
    if not value:
        return "—"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL).strftime("%H:%M:%S")


def local_stamp(value: str | None) -> str:
    if not value:
        return "—"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M")


def one_line(value: str) -> str:
    return " ".join(value.split())


def text_of(message: dict[str, object] | None) -> str:
    if message is None:
        return "（没有对应消息）"
    content = one_line(str(message.get("content") or "")) or "（空）"
    status = str(message.get("status") or "")
    if status not in {"recorded", "completed"}:
        content = f"{content}〔{status}〕"
    return content


def proposal_part(decision: dict[str, object], group: str, key: str) -> str:
    proposal = decision.get("model_proposal")
    if not isinstance(proposal, dict):
        return "—"
    nested = proposal.get(group)
    if not isinstance(nested, dict):
        return "—"
    value = nested.get(key)
    if value is None or str(value).strip() == "":
        return "—"
    return str(value).strip()


def topic_text(decision: dict[str, object]) -> str:
    topic = decision.get("topic")
    if not isinstance(topic, dict):
        return "—"
    topic_id = topic.get("topic_id") or "—"
    transition = topic.get("transition") or "—"
    return f"{topic_id} / {transition}"


def motivation_text(decision: dict[str, object]) -> str:
    motivation = decision.get("motivation")
    if not isinstance(motivation, dict):
        return "—"
    primary = one_line(str(motivation.get("primary") or ""))
    summary = one_line(str(motivation.get("summary") or ""))
    if primary and summary:
        joiner = "" if primary.endswith(("。", "！", "？")) else "。"
        return f"{primary}{joiner}{summary}"
    return primary or summary or "—"


def validation_text(decision: dict[str, object]) -> str:
    validation = decision.get("validation_result")
    if not isinstance(validation, dict) or not validation:
        return "—"
    kept = {key: value for key, value in validation.items() if key in {"accepted", "fallback", "blocked", "should_send"}}
    return json.dumps(kept or validation, ensure_ascii=False)


def render_decision(index: int, decision: dict[str, object], messages: dict[str, dict[str, object]]) -> list[str]:
    trigger = messages.get(str(decision.get("trigger_message_id")))
    result = messages.get(str(decision.get("result_message_id")))
    secondary = decision.get("secondary_actions") or []
    secondary_text = "、".join(str(item) for item in secondary) if secondary else "无"
    lines = [
        f"### {index}. {local_time(str(decision.get('created_at')))} {decision.get('trigger_type')} → {decision.get('primary_action')}",
        "",
        f"- 触发：{text_of(trigger)}",
        f"- 回复：{text_of(result) if decision.get('result_message_id') else '没有发出消息'}",
        f"- 状态：{decision.get('status')}，置信度 {decision.get('confidence')}",
        f"- 辅助行为：{secondary_text}",
        f"- 动机：{motivation_text(decision)}",
        f"- 用户需求：{proposal_part(decision, 'user_need', 'summary')}",
        f"- 自身兴趣：{proposal_part(decision, 'self_motivation', 'interest')}",
        f"- 自身观点：{proposal_part(decision, 'self_motivation', 'viewpoint')}",
        f"- 表达欲望：{proposal_part(decision, 'self_motivation', 'desire_to_express')}",
        f"- 话题：{topic_text(decision)}",
        f"- 理由：{one_line(str(decision.get('reasoning_summary') or '')) or '—'}",
        f"- 校验：{validation_text(decision)}",
        "",
    ]
    return lines


def render() -> str:
    companions = load()
    lines = [
        "# 艺 · 全部对话与决策记录",
        "",
        "导出时间以北京时间为准。库里有三名都叫「艺」的陪伴者，人格不同，下面分开记录。",
        "",
    ]
    for companion in companions:
        conversations = companion.get("conversations") or []
        message_count = sum(len(item.get("messages") or []) for item in conversations)
        decision_count = sum(len(item.get("decisions") or []) for item in conversations)
        lines.extend(
            [
                f"## {companion.get('mbti_type')} · {companion.get('name')}",
                "",
                f"- 陪伴者 `{companion.get('id')}`",
                f"- 用户 {companion.get('owner_name')} `{companion.get('owner_user_id')}`",
                f"- 创建于 {local_stamp(str(companion.get('created_at')))}",
                f"- {len(conversations)} 段会话，{message_count} 条消息，{decision_count} 次决策",
                "",
            ]
        )
        if not conversations:
            lines.extend(["没有会话。", ""])
            continue
        for conversation in conversations:
            messages = conversation.get("messages") or []
            decisions = conversation.get("decisions") or []
            by_id = {str(item.get("id")): item for item in messages}
            lines.extend(
                [
                    f"### 会话 {conversation.get('title') or '未命名'}",
                    "",
                    f"`{conversation.get('id')}` · {conversation.get('status')} · {local_stamp(str(conversation.get('created_at')))} · {len(messages)} 条消息 · {len(decisions)} 次决策",
                    "",
                    "#### 对话原文",
                    "",
                ]
            )
            if not messages:
                lines.append("没有消息。")
                lines.append("")
            for message in messages:
                speaker = SENDER.get(str(message.get("sender_type")), str(message.get("sender_type")))
                content = str(message.get("content") or "").replace("\r\n", "\n").strip() or "（空）"
                status = str(message.get("status") or "")
                if status not in {"recorded", "completed"}:
                    content = f"{content}〔{status}〕"
                first, *rest = content.split("\n")
                lines.append(
                    f"{message.get('sequence_number')}. {local_time(str(message.get('created_at')))} {speaker}：{first}"
                )
                lines.extend(f"   {line}" for line in rest)
            lines.extend(["", "#### 决策过程", ""])
            if not decisions:
                lines.extend(["这段会话没有决策。", ""])
                continue
            for index, decision in enumerate(decisions, start=1):
                lines.extend(render_decision(index, decision, by_id))
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(OUT)
