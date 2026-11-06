import json

from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, RECENT_MESSAGE_LIMIT
from app.modules.model_adapter.domain.messages import ChatMessage

_DECISION_SYSTEM = (
    "你只输出一个 JSON 对象，不要输出其他文字。"
    "JSON 只能包含 should_send、primary_action、secondary_actions、motivation、topic、confidence、reasoning_summary。"
    "should_send 是布尔值。secondary_actions 是字符串数组，可以是空数组。"
    "motivation 是对象，包含 primary 和 summary。topic 是对象，包含 topic_id 和 transition。"
    "transition 只能是 continue、new_topic、close、none 或 null。confidence 是 0 到 1 的数字。"
    "不要增加其他字段。"
    "primary_action 只能是 respond、share、ask、react、continue、close、quiet 之一。"
    "只能有一个主要行为。Quiet 不能搭配其他行为，并且 should_send 必须为 false。"
    "不要编造没有提供的经历或记忆，不要威胁、羞辱或控制用户。"
    "immediate_facts 只是当前用户消息里的即时事实，不是长期记忆。"
    "memories 里 is_inference 为 true 的内容是推断，不能写成用户明确说过的事实。"
    "候选记忆可以参考，但它还不是正式长期记忆。"
    "working_memory 只描述当前会话，attention_topics 是长期关注，二者都不是用户明确说过的事实。"
)

_REALIZATION_SYSTEM = (
    "按照已经确定的决策写一条要发送的消息。"
    "不要改变主要行为，不要把决定改成安静，也不要追加新的决定。"
    "不要编造没有提供的经历。只输出消息正文。"
    "推断性记忆不能写成用户明确说过的事实。即时事实只来自当前消息。"
)


def decision_messages(
    *,
    mbti_type: str,
    core_traits: dict[str, object],
    communication_preferences: dict[str, object],
    emotion_primary: str,
    emotion_cause: str,
    relationship_summary: str,
    interaction_mode: str,
    proactive_allowed: bool,
    recent_messages: list[dict[str, str]],
    repair: bool,
    memories: list[dict[str, object]] | None = None,
    immediate_facts: list[dict[str, str]] | None = None,
    working_memory: dict[str, object] | None = None,
    attention_topics: list[dict[str, object]] | None = None,
) -> list[ChatMessage]:
    context = {
        "persona": {
            "mbti_type": mbti_type,
            "core_traits": core_traits,
            "communication_preferences": communication_preferences,
        },
        "state": {
            "emotion_primary": emotion_primary,
            "emotion_cause": emotion_cause,
            "relationship_summary": relationship_summary,
            "interaction_mode": interaction_mode,
            "proactive_allowed": proactive_allowed,
        },
        "immediate_facts": immediate_facts or [],
        "working_memory": working_memory,
        "attention_topics": attention_topics or [],
        "memories": memories or [],
        "recent_messages": recent_messages[-RECENT_MESSAGE_LIMIT:],
    }
    messages = [
        ChatMessage(role="system", content=_DECISION_SYSTEM),
        ChatMessage(role="user", content=json.dumps(context, ensure_ascii=False)),
    ]
    if repair:
        messages.append(ChatMessage(role="user", content="上一次输出不符合结构。请只返回一个符合字段的 JSON 对象。"))
    return messages


def realization_messages(
    suggestion: ModelDecisionSuggestion,
    recent_messages: list[dict[str, str]],
    memories: list[dict[str, object]] | None = None,
    immediate_facts: list[dict[str, str]] | None = None,
) -> list[ChatMessage]:
    brief = {
        "primary_action": suggestion.primary_action.value,
        "secondary_actions": [item.value for item in suggestion.secondary_actions],
        "motivation": suggestion.motivation.model_dump(mode="json"),
        "topic": suggestion.topic.model_dump(mode="json"),
        "reasoning_summary": suggestion.reasoning_summary,
        "immediate_facts": immediate_facts or [],
        "memories": memories or [],
        "recent_messages": recent_messages[-RECENT_MESSAGE_LIMIT:],
    }
    return [
        ChatMessage(role="system", content=_REALIZATION_SYSTEM),
        ChatMessage(role="user", content=json.dumps(brief, ensure_ascii=False)),
    ]


def final_send(suggestion: ModelDecisionSuggestion) -> tuple[DialogueAction, bool]:
    """Quiet 或不发送时，最终行为是 Quiet，并且不生成消息。"""
    if suggestion.primary_action == DialogueAction.QUIET or not suggestion.should_send:
        return DialogueAction.QUIET, False
    return suggestion.primary_action, True
