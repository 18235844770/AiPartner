"""口语回合的篇幅和套话检查。六种人格共用，不调用模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.speech_marks import strip_non_speech_marks

_SENTENCE_END = re.compile(r"[。！？!?]+")

# 开场或交代。用户原文含「接住」时，不把「接住了」算作套话。
_STOCK_PHRASES = (
    "接住了",
    "我听见了",
    "我收到了",
    "这一声我",
    "我在这儿听",
    "你继续",
    "我不打岔",
    "心里被碰到",
    "像窗户被推开",
)

# 把决策原因说出来。
_REASON_PHRASES = (
    "所以我选择",
    "我分得清",
    "我不催你",
    "不找方案就不找方案",
    "不给你塞方案",
    "不塞方案",
    "不给方案",
    "不是因为你说了",
    "我心里有数",
    "我在这儿",
    "不糊弄你",
    "我不会因此",
    "那我安静了",
    "不缠着你",
    "先不聊了",
    "那就不聊",
    "不劝",
    "不替你拿主意",
    "是你自己的事",
    "我就在这儿等",
    "停在这儿",
    "没觉得被落下",
    "安静听你说",
)
_AGREEMENT_FILLERS = ("太会了", "这种感觉我懂", "我懂啊", "太正常了", "比你想的", "深有同感")
_LOOSE_CHARS = re.compile(r"[都了呢啊吧嘛呀]")

_BARE_ACKS = frozenset({"嗯", "哦", "啊", "噢", "唔", "好", "行", "嗯嗯", "哦哦", "啊啊", "好的", "行吧", "知道了"})
_SOCIAL_SIGNALS = frozenset({"哈哈", "哈哈哈", "哈哈哈哈", "呵呵", "嘿嘿", "嘿嘿嘿"})
_GREETING_PREFIXES = ("嗨", "你好", "哈喽", "早上好", "下午好", "晚上好", "早安", "晚安")
_PUNCT = re.compile(r"[\s，。！？、~～!?.,…·]+")
# 用户把话口封住，或这一轮不该再探。
_BLOCK_PROBE = (
    "别问",
    "别分析",
    "别劝",
    "别评价",
    "不用说",
    "不聊",
    "先别回",
    "别回我",
    "我先睡",
    "晚安",
    "不是来找方案",
    "想骂",
    "就想说一句",
    "就想抱怨",
)
# 用户在问该怎么做。
_GUIDANCE_MARKS = ("应该", "要不要", "怎么办", "怎么做", "该不该", "拿个主意", "给个方案", "给个建议")
_DODGE_GUIDANCE = ("没替你做决定", "不替你拿主意", "不替你决定", "没替你决定")
_LIVED_EXPERIENCE = (
    "跟着哼",
    "播到下一段",
    "听着听着",
    "戴着耳机",
    "看到你",
    "看着你",
    "捧在手里",
    "昨晚我听",
    "我去过",
)
_TENDER_FILLERS = ("心疼", "别硬撑", "好好歇", "我陪着你", "我陪你坐")
_SELF_CLAIM = ("还没散", "完全散", "我自己慢慢", "我还挂着", "那点烦还")
_SLEEP_WISH = ("还想", "有一点", "舍不得")
_CLOSE_MARKS = ("我先睡了", "今天就这样", "今天就到这", "今天就到这儿", "先睡了", "晚安")
_CLOSE_HYPOTHETICAL = ("要是", "如果", "会不会", "会觉得", "要不要")


@dataclass(frozen=True)
class TurnShape:
    max_sentences: int
    max_questions: int
    max_chars: int | None = None


def is_bare_acknowledgement(text: str) -> bool:
    return _compact(text) in _BARE_ACKS


def is_social_signal(text: str) -> bool:
    return _compact(text) in _SOCIAL_SIGNALS


def blocks_probe(text: str) -> bool:
    return any(mark in text for mark in _BLOCK_PROBE)


def asks_for_guidance(text: str) -> bool:
    """用户在问应不应该、要不要、怎么办。明确拒绝建议时不算。"""
    if blocks_probe(text):
        return False
    return any(mark in text for mark in _GUIDANCE_MARKS)


def opens_topic(text: str) -> bool:
    """用户抛出一段还没展开的情况，可以就内容问一句。"""
    raw = text.strip()
    if not raw or blocks_probe(raw) or asks_for_guidance(raw) or _is_question(raw):
        return False
    if is_bare_acknowledgement(raw) or is_social_signal(raw) or _is_short_greeting(raw):
        return False
    return len(_compact(raw)) >= 8


def build_turn_shape(primary_action: str, user_text: str) -> TurnShape:
    """按主要行为和用户这句话定句数、问句上限。

    放出话题时可以有一个针对内容的问题。用户在问方案时给判断，不再加问句。
    附和、笑声、打招呼、封口和收束不问。
    """
    text = user_text.strip()
    asked = _is_question(text)
    if is_bare_acknowledgement(text) and not asked:
        return TurnShape(max_sentences=1, max_questions=0, max_chars=8)
    if is_social_signal(text):
        return TurnShape(max_sentences=2, max_questions=0, max_chars=24)
    if _is_short_greeting(text) and not asked:
        return TurnShape(max_sentences=1, max_questions=0, max_chars=24)
    if asks_for_guidance(text):
        return TurnShape(max_sentences=4, max_questions=0)
    questions = 1 if opens_topic(text) or (primary_action == "ask" and not blocks_probe(text)) else 0
    if primary_action in {"share", "ask"} or asked:
        return TurnShape(max_sentences=4, max_questions=questions)
    if primary_action in {"react", "continue", "close", "quiet"} or len(text) <= 12:
        return TurnShape(max_sentences=2, max_questions=questions)
    if primary_action == "respond" and len(text) <= 40:
        return TurnShape(max_sentences=2, max_questions=questions)
    return TurnShape(max_sentences=3, max_questions=questions)


def is_user_closing(text: str) -> bool:
    """用户在结束这次对话，不是在假设如果去睡会怎样。"""
    if any(mark in text for mark in _CLOSE_HYPOTHETICAL):
        return False
    return any(mark in text for mark in _CLOSE_MARKS)


def speech_issues(
    text: str,
    shape: TurnShape,
    user_text: str,
    *,
    emotion_ownership: str | None = None,
) -> list[str]:
    """返回这一稿违反口语回合的条目。空列表表示可以通过。"""
    body = text.strip()
    if not body:
        return []
    issues: list[str] = []
    spoken = strip_non_speech_marks(body)
    if not spoken:
        issues.append("只有表情，没有要说的话")
        return issues
    sentences = _sentence_count(spoken)
    if sentences > shape.max_sentences:
        issues.append(f"超过 {shape.max_sentences} 句")
    if shape.max_chars is not None and len(spoken) > shape.max_chars:
        issues.append(f"超过 {shape.max_chars} 字")
    questions = spoken.count("？") + spoken.count("?")
    if questions > shape.max_questions:
        if shape.max_questions == 0:
            issues.append("这一轮不问")
        else:
            issues.append(f"问句超过 {shape.max_questions} 个")
    user_said_receive = "接住" in user_text
    for phrase in _STOCK_PHRASES:
        if phrase == "接住了" and user_said_receive:
            continue
        if phrase in body:
            issues.append(f"使用了套话「{phrase}」")
    for phrase in _REASON_PHRASES:
        if phrase in body:
            issues.append(f"说出了决策原因「{phrase}」")
    if asks_for_guidance(user_text):
        for phrase in _DODGE_GUIDANCE:
            if phrase in body:
                issues.append(f"用户在问该怎么做，却只说了「{phrase}」")
    if re.search(r"我还在(?!想)", body):
        issues.append("说出了决策原因「我还在」")
    echoed = _echoed_chunk(spoken, user_text)
    if echoed:
        issues.append(f"把对方的话又说了一遍「{echoed}」")
    for phrase in _AGREEMENT_FILLERS:
        if phrase in spoken:
            issues.append(f"附和过多「{phrase}」")
    if spoken.startswith("会啊") and len(spoken) > 18:
        issues.append("用附和把话铺长了")
    for phrase in _LIVED_EXPERIENCE:
        if phrase in spoken:
            issues.append(f"把没发生的经历说成了自己的「{phrase}」")
    for phrase in _TENDER_FILLERS:
        if phrase in spoken:
            issues.append(f"默认体贴「{phrase}」")
    if emotion_ownership != "self":
        for phrase in _SELF_CLAIM:
            if phrase in spoken:
                issues.append(f"把对方的情绪说成自己还留着「{phrase}」")
    if is_user_closing(user_text):
        if not any(mark in spoken for mark in _SLEEP_WISH):
            issues.append("结束时没有说出自己的一点意愿")
        if "睡" not in spoken and "晚安" not in spoken:
            issues.append("结束时没有让对方去睡")
    return issues


def speech_repair_message(issues: list[str]) -> str:
    detail = "；".join(issues)
    return (
        f"上一稿违反了口语回合：{detail}。"
        "只重写正文，不要改变已经确定的行为，不要解释这些原因。"
    )


def current_user_text(
    immediate_facts: list[dict[str, str]],
    recent_messages: list[dict[str, str]],
) -> str:
    for item in reversed(immediate_facts):
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    for item in reversed(recent_messages):
        sender = item.get("sender_type") or item.get("role")
        if sender != "user":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _is_question(text: str) -> bool:
    return "？" in text or "?" in text


def _compact(text: str) -> str:
    return _PUNCT.sub("", text.strip())


def _loose(text: str) -> str:
    compact = _compact(text)
    for token in sorted(_SOCIAL_SIGNALS, key=len, reverse=True):
        compact = compact.replace(token, "")
    return _LOOSE_CHARS.sub("", compact)


def _echoed_chunk(reply: str, user_text: str) -> str | None:
    """对方原话里连续 6 个字又出现在回复里，视为把话再说一遍。"""
    left = _loose(user_text)
    right = _loose(reply)
    if len(left) < 6 or len(right) < 6:
        return None
    longest = ""
    upper = min(10, len(left))
    for size in range(upper, 5, -1):
        for index in range(0, len(left) - size + 1):
            chunk = left[index : index + size]
            if chunk in right and len(chunk) > len(longest):
                longest = chunk
        if longest:
            return longest
    return None


def _is_short_greeting(text: str) -> bool:
    if len(text.strip()) > 16:
        return False
    core = _compact(text)
    return any(core.startswith(item) for item in _GREETING_PREFIXES)


def _sentence_count(text: str) -> int:
    parts = [part.strip() for part in _SENTENCE_END.split(text)]
    count = sum(1 for part in parts if part)
    if count == 0 and text.strip():
        return 1
    return count
