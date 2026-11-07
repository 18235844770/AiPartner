"""Quiet 过用闸：有实质交流需求时禁止 Quiet，连续 Quiet 强制回应。"""

from __future__ import annotations

from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion

# 同会话连续 Quiet 达到该次数后，下一轮用户消息禁止再 Quiet（除非用户明确要求沉默）。
MAX_CONSECUTIVE_QUIET = 1

_SILENCE_REQUESTS = (
    "先别回",
    "别回了",
    "不用回",
    "不必回",
    "不用回复",
    "先别说话",
    "别说话",
    "稍后说",
    "一会儿再说",
    "我先安静",
    "你安静",
    "保持安静",
    "先闭嘴",
)

_ENDING_CUES = (
    "晚安",
    "拜拜",
    "再见",
    "先这样",
    "就这样吧",
    "我去忙",
    "我去睡觉",
    "回头聊",
    "改天聊",
)

_GREETINGS = (
    "你好",
    "嗨",
    "哈喽",
    "hello",
    "hi",
    "在吗",
    "早上好",
    "下午好",
    "晚上好",
)

_EMOTION_SHARE = (
    "难过",
    "开心",
    "害怕",
    "焦虑",
    "不安",
    "委屈",
    "生气",
    "郁闷",
    "想你",
    "想念",
    "喜欢你",
    "爱你",
    "心情",
    "心里",
    "难受",
    "孤独",
    "寂寞",
    "压力",
)

_RELATIONSHIP_CUES = (
    "我们",
    "陪我",
    "在不在",
    "理我",
    "关心我",
    "在意我",
    "分手",
    "喜欢你",
    "爱你",
)

_REQUEST_CUES = (
    "帮我",
    "告诉我",
    "跟我说",
    "你说",
    "聊聊",
    "听我说",
    "想听听",
    "请你",
)


def user_requests_silence(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return any(cue in lowered for cue in _SILENCE_REQUESTS)


def requires_response(text: str) -> bool:
    """用户消息含问句、请求、情绪/关系表达、问候时，必须回应。"""
    stripped = text.strip()
    if not stripped:
        return False
    if user_requests_silence(stripped):
        return False
    lowered = stripped.lower()
    if "?" in stripped or "？" in stripped:
        return True
    if any(cue in lowered for cue in _GREETINGS):
        return True
    if any(cue in lowered for cue in _REQUEST_CUES):
        return True
    if any(cue in lowered for cue in _EMOTION_SHARE):
        return True
    if any(cue in lowered for cue in _RELATIONSHIP_CUES):
        return True
    if _looks_like_question(stripped):
        return True
    return False


def is_substantive_share(text: str) -> bool:
    """用户在分享观点或经历，不能因为话说完了就 Quiet。明确收尾除外。"""
    stripped = text.strip()
    if len(stripped) < 8:
        return False
    if user_requests_silence(stripped):
        return False
    lowered = stripped.lower()
    if any(cue in lowered for cue in _ENDING_CUES) and len(stripped) < 24:
        return False
    return True


def apply_quiet_gate(
    suggestion: ModelDecisionSuggestion,
    *,
    user_message: str | None,
    consecutive_quiet: int,
    user_triggered: bool,
) -> tuple[ModelDecisionSuggestion, dict[str, object]]:
    """对用户触发的 Quiet 建议做硬规则校验。主动触发不受此闸限制。"""
    if not user_triggered:
        return suggestion, {}
    quiet_like = suggestion.primary_action == DialogueAction.QUIET or not suggestion.should_send
    if not quiet_like:
        meta: dict[str, object] = {"quiet_gate": "pass"}
        if consecutive_quiet > 0:
            meta["consecutive_quiet_reset"] = True
        return suggestion, meta

    message = (user_message or "").strip()
    if user_requests_silence(message):
        forced = _ensure_quiet(suggestion)
        return forced, {"quiet_gate": "allowed_silence_request", "should_send": False}

    if requires_response(message):
        forced = _force_respond(suggestion, "用户消息需要回应，不能 Quiet")
        return forced, {"quiet_gate": "forced_requires_response", "should_send": True}

    if consecutive_quiet >= MAX_CONSECUTIVE_QUIET:
        forced = _force_respond(suggestion, "连续 Quiet 已达上限，本轮必须回应")
        return forced, {
            "quiet_gate": "forced_consecutive_quiet",
            "consecutive_quiet": consecutive_quiet,
            "should_send": True,
        }

    if is_substantive_share(message):
        forced = _force_respond(suggestion, "用户在分享实质内容，不能当作对话结束")
        return forced, {"quiet_gate": "forced_substantive_share", "should_send": True}

    return _ensure_quiet(suggestion), {"quiet_gate": "allowed", "should_send": False}


def _force_respond(suggestion: ModelDecisionSuggestion, note: str) -> ModelDecisionSuggestion:
    reason = suggestion.reasoning_summary
    if note not in reason:
        reason = f"{reason}；{note}"
    return suggestion.model_copy(
        update={
            "should_send": True,
            "primary_action": DialogueAction.RESPOND,
            "secondary_actions": [],
            "reasoning_summary": reason,
        }
    )


def _ensure_quiet(suggestion: ModelDecisionSuggestion) -> ModelDecisionSuggestion:
    if suggestion.primary_action == DialogueAction.QUIET and not suggestion.should_send:
        return suggestion
    return suggestion.model_copy(
        update={
            "should_send": False,
            "primary_action": DialogueAction.QUIET,
            "secondary_actions": [],
        }
    )


def _looks_like_question(text: str) -> bool:
    starters = ("为什么", "怎么", "如何", "是否", "能不能", "可不可以", "会不会", "有没有", "什么")
    return any(text.startswith(item) or f" {item}" in f" {text}" for item in starters)
