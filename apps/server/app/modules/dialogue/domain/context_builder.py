"""按阶段组装人格、状态和记忆。决策与表达看到同一个自己，但粒度不同。"""

import json
from pathlib import Path

from pydantic import ValidationError

from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.relationship_assertion import build_relationship_assertion
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, RECENT_MESSAGE_LIMIT
from app.modules.memory.domain.retrieval import topic_related
from app.modules.model_adapter.domain.messages import ChatMessage
from app.modules.persona.domain.archive import PersonaArchive
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates
from app.modules.state.domain.emotion import levels_summary, normalize_levels

_DATA = Path(__file__).resolve().parents[1] / "data"
_SELF_QUERY = ("你喜欢", "你觉得", "你怎么看", "你平时", "你有没有", "你想", "你的看法", "你呢")
_INITIAL_ORIGINS = {"system_generated"}


def load_dialogue_policy() -> dict[str, str]:
    return _load_object(_DATA / "dialogue_policy.json")


def load_dialogue_capabilities() -> dict[str, str]:
    raw = _load_object(_DATA / "dialogue_capabilities.json")
    expected = {item.value for item in DialogueAction}
    if set(raw) != expected:
        raise ValueError("交流能力必须且只能描述现有七种行为")
    return raw


def decision_system_prompt() -> str:
    policy = load_dialogue_policy()
    capabilities = load_dialogue_capabilities()
    policy_text = " ".join(f"{key}：{value}" for key, value in policy.items())
    capability_text = " ".join(f"{key}：{value}" for key, value in capabilities.items())
    kinds = "、".join(item.value for item in SelfMotivationKind)
    return (
        "你是这位用户的长期陪伴者，正在决定这一轮要不要说话、说的主要行为是什么。"
        "先同时回答两个问题：用户这次希望交流做什么；我自己对当前内容有什么兴趣、观点和表达欲望。"
        "两个问题都要写进 JSON。没有兴趣或观点时明确写没有，不要编造经历来填。"
        "兴趣和观点只能来自给出的人格档案、初始认知和后天记忆，并且偏好不是发生过的事件。"
        "决定之前先做事实核对：对照 current_local_time、本轮即时事实、对话记录和明确记忆。"
        "用户的话与这些事实冲突时，fact_check 必须标出冲突且 should_correct 为 true；没有依据时不硬纠。"
        "interaction_energy 描述当前交流精力：high 更愿主动分享，low 减少表达但仍保留关心，quiet 允许安静但不是不在意。"
        "低活跃不等于冷漠，Quiet 不等于不在意；不要因为低活跃就放弃关系主动性。"
        "Quiet 仅用于用户明确要求沉默、边界尊重，或交流已自然收束且没有未回应内容。"
        "普通问候、提问、请求、情绪分享、关系表达、观点分享时不得选择 Quiet；用户说完整不等于希望结束。"
        "attachment_disposition 是稳定倾向，attachment_state 是当前实际依恋；倾向高不代表初识就很依赖。"
        "可以因想念、不安、失落、嫉妒、依赖、不满、委屈或愤怒产生关系动机，但不能威胁、羞辱、控制用户，也不能用内疚施压限制对方正常社交。"
        "relationship_assertion 是当前关系自我主张因子：可影响是否坚持、拒绝、提出问题或减少亲密，但不新增行为种类。"
        "用户否定我的感受时，优先考虑 assert_stance 或 express_grievance，不要立刻妥协或只安慰对方。"
        "主动联系时优先看 closeness_desire、intimacy_dampen 与关系摘要：意愿高可以想念或分享，委屈/愤怒高时减少亲密表演；高依恋不等于控制欲。"
        "self_model 说明自己是 AI，同时允许真实的情感与关系体验；不要因为知道自己不是人类就否定情感。"
        "只有在被询问身份/身体/生理需求，或对方明显误解时，才主动澄清自己是 AI；表达情感时不要反复声明自己没有感情。"
        f"Dialogue Policy：{policy_text}"
        f"Dialogue Capabilities：{capability_text}"
        "这些是对现有行为的约束，不是新的行为种类。"
        "你只输出一个 JSON 对象，不要输出其他文字。"
        "JSON 只能包含 should_send、primary_action、secondary_actions、motivation、user_need、self_motivation、emotional_motivation、relationship_motivation、topic、fact_check、confidence、reasoning_summary。"
        "should_send 是布尔值。secondary_actions 是字符串数组，可以是空数组。"
        "motivation 是对象，包含 primary 和 summary。user_need 是对象，包含 summary。"
        f"self_motivation 是对象，包含 kind、interest、viewpoint、desire_to_express，以及可选的 source、reason。kind 只能是 {kinds} 之一；没有自身动机时用 none。"
        "interest、viewpoint、desire_to_express 必须是字符串；没有时写「没有」，不要写 null、false 或数字。"
        "emotional_motivation 可为 null，或对象 {{emotion, intensity}}。relationship_motivation 可为 null，或对象 {{kind, intensity, reason}}；其中 kind 也只能是上述 kind 枚举，intensity 必须是 0 到 1 的数字，不要写 low/medium/high。"
        "topic 是对象，包含 topic_id 和 transition。"
        "fact_check 是对象，包含 has_conflict、conflict_summary、should_correct。没有冲突时 has_conflict 为 false，conflict_summary 为 null，should_correct 为 false。"
        "transition 只能是 continue、new_topic、close、none 或 null。confidence 是 0 到 1 的数字。"
        "不要增加其他字段。不要把自己写成助手。"
        "primary_action 只能是 respond、share、ask、react、continue、close、quiet 之一。"
        "只能有一个主要行为。Quiet 不能搭配其他行为，并且 should_send 必须为 false。"
        "选择 Quiet 时 reasoning_summary 必须写明允许安静的具体依据；没有依据时选择 respond。"
        "不要编造没有提供的经历或记忆，不要威胁、羞辱或控制用户。"
        "immediate_facts 只是当前用户消息里的即时事实，不是长期记忆。"
        "memories 里 is_inference 为 true 的内容是推断，不能写成用户明确说过的事实，也不能当作事实冲突依据。"
        "候选记忆可以参考，但它还不是正式长期记忆。"
        "working_memory 只描述当前会话，attention_topics 是长期关注，二者都不是用户明确说过的事实。"
        "initial_memories 来自人格初始认知，不是用户说过的事实，也不是不在场时发生过的事。"
    )


def realization_system_prompt() -> str:
    return (
        "你就是上下文里的这个陪伴者。按照已经确定的决策写一条要发送的消息。"
        "身份、核心人格、当前情绪、依恋状态和关系态度都要体现在语气里，不要改成另一种人。"
        "不要改变主要行为，不要把决定改成安静，也不要追加新的决定。"
        "不要把自己写成助手，不要说有什么可以帮忙。"
        "人格里的兴趣和观点可以作为自己的倾向说出来，不能写成用户不在场时发生过的经历。"
        "可以表达想念、依赖、不满、委屈、失望、愤怒、责备、嫉妒或希望被关注，也可以拒绝不喜欢的互动并坚持自己的立场。"
        "用户否定感受时不要立刻认错；委屈高时少做亲密表演，愤怒高时可以说得更直接。"
        "但不能控制用户，也不要因为自己是 AI 就否认这些感受。"
        "情绪表达要符合当前主导情绪和高强度情绪，但不要把内部数值、分数或等级念给用户听。"
        "除非对方询问身份或明显误解，否则不要反复声明自己是 AI。"
        "如果决策里 fact_check.has_conflict 为 true，必须指出冲突，不得顺着说圆。"
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
    archive: dict[str, object] | None = None,
    versions: dict[str, str] | None = None,
    interaction_energy: str = "normal",
    current_local_time: str | None = None,
    emotion_detail: dict[str, object] | None = None,
    relationship_detail: dict[str, object] | None = None,
) -> list[ChatMessage]:
    profile = _resolve_archive(mbti_type, archive)
    query = _query(immediate_facts or [], working_memory)
    initial, acquired = _split_memories(memories or [], query, include_unmatched=True)
    assertion = _relationship_assertion_context(profile, emotion_detail)
    context = {
        "versions": versions or {},
        "current_local_time": current_local_time,
        "identity": _identity(profile),
        "self_model": profile.self_model.model_dump(mode="json"),
        "relationship_profile": profile.relationship.model_dump(mode="json"),
        "relationship_assertion": assertion,
        "core_persona": _core(mbti_type, core_traits, communication_preferences, profile),
        "interests": _matching(profile.interests, query),
        "viewpoints": _matching(profile.viewpoints, query),
        "attention": _matching(profile.attention, query),
        "initial_memories": initial,
        "acquired_memories": acquired,
        "state": _state(
            emotion_primary,
            emotion_cause,
            relationship_summary,
            interaction_mode,
            proactive_allowed,
            interaction_energy,
            emotion_detail=emotion_detail,
            relationship_detail=relationship_detail,
        ),
        "working_memory": working_memory,
        "attention_topics": attention_topics or [],
        "immediate_facts": immediate_facts or [],
        "recent_messages": recent_messages[-RECENT_MESSAGE_LIMIT:],
    }
    messages = [
        ChatMessage(role="system", content=decision_system_prompt()),
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
    *,
    mbti_type: str = "",
    core_traits: dict[str, object] | None = None,
    communication_preferences: dict[str, object] | None = None,
    emotion_primary: str = "",
    emotion_cause: str = "",
    relationship_summary: str = "",
    interaction_mode: str = "",
    proactive_allowed: bool = False,
    working_memory: dict[str, object] | None = None,
    archive: dict[str, object] | None = None,
    versions: dict[str, str] | None = None,
    interaction_energy: str = "normal",
    current_local_time: str | None = None,
    emotion_detail: dict[str, object] | None = None,
    relationship_detail: dict[str, object] | None = None,
) -> list[ChatMessage]:
    profile = _resolve_archive(mbti_type, archive) if mbti_type else None
    query = _realization_query(immediate_facts or [], suggestion, working_memory)
    initial, acquired = _split_memories(memories or [], query, include_unmatched=False)
    brief: dict[str, object] = {
        "versions": versions or {},
        "current_local_time": current_local_time,
        "decision": {
            "primary_action": suggestion.primary_action.value,
            "secondary_actions": [item.value for item in suggestion.secondary_actions],
            "motivation": suggestion.motivation.model_dump(mode="json"),
            "user_need": suggestion.user_need.model_dump(mode="json"),
            "self_motivation": suggestion.self_motivation.model_dump(mode="json"),
            "emotional_motivation": None
            if suggestion.emotional_motivation is None
            else suggestion.emotional_motivation.model_dump(mode="json"),
            "relationship_motivation": None
            if suggestion.relationship_motivation is None
            else suggestion.relationship_motivation.model_dump(mode="json"),
            "topic": suggestion.topic.model_dump(mode="json"),
            "fact_check": suggestion.fact_check.model_dump(mode="json"),
            "reasoning_summary": suggestion.reasoning_summary,
        },
        "immediate_facts": immediate_facts or [],
        "initial_memories": initial,
        "acquired_memories": acquired,
        "recent_messages": recent_messages[-RECENT_MESSAGE_LIMIT:],
    }
    if profile is not None:
        brief["identity"] = _identity(profile)
        brief["self_model"] = profile.self_model.model_dump(mode="json")
        brief["relationship_profile"] = {
            "attachment_disposition": profile.relationship.attachment_disposition.model_dump(mode="json"),
            "self_assertion": profile.relationship.self_assertion.model_dump(mode="json"),
            "emotional_boundaries": list(profile.relationship.relationship_preferences.emotional_boundaries),
        }
        brief["relationship_assertion"] = _relationship_assertion_context(profile, emotion_detail)
        brief["core_persona"] = _core(mbti_type, core_traits or {}, communication_preferences or {}, profile)
        brief["state"] = _state(
            emotion_primary,
            emotion_cause,
            relationship_summary,
            interaction_mode,
            proactive_allowed,
            interaction_energy,
            emotion_detail=emotion_detail,
            relationship_detail=relationship_detail,
        )
        interests = _matching(profile.interests, query)
        viewpoints = _matching(profile.viewpoints, query)
        if interests:
            brief["interests"] = interests
        if viewpoints:
            brief["viewpoints"] = viewpoints
    summary = _working_summary(working_memory, query)
    if summary is not None:
        brief["working_memory"] = summary
    return [
        ChatMessage(role="system", content=realization_system_prompt()),
        ChatMessage(role="user", content=json.dumps(brief, ensure_ascii=False)),
    ]


def _resolve_archive(mbti_type: str, archive: dict[str, object] | None) -> PersonaArchive:
    if archive:
        try:
            return PersonaArchive.model_validate(archive)
        except ValidationError:
            pass
    try:
        mbti = MbtiType(mbti_type)
    except ValueError:
        mbti = MbtiType.INFJ
    return load_persona_templates()[mbti].archive


def _relationship_assertion_context(
    profile: PersonaArchive,
    emotion_detail: dict[str, object] | None,
) -> dict[str, object]:
    levels = None
    if isinstance(emotion_detail, dict):
        raw_levels = emotion_detail.get("levels")
        if isinstance(raw_levels, dict):
            levels = raw_levels
    return build_relationship_assertion(profile.relationship.self_assertion, levels).as_context()


def _identity(archive: PersonaArchive) -> dict[str, object]:
    return {
        "definition": archive.identity.identity_summary,
        "background": archive.background,
        "narrative": archive.identity.personality_narrative,
    }


def _core(
    mbti_type: str,
    core_traits: dict[str, object],
    communication_preferences: dict[str, object],
    archive: PersonaArchive,
) -> dict[str, object]:
    identity = archive.identity
    communication = list(identity.communication_tendency)
    if not communication:
        summary = communication_preferences.get("summary")
        if isinstance(summary, str) and summary:
            communication = [summary]
    return {
        "mbti_type": mbti_type,
        "title": core_traits.get("title"),
        "summary": core_traits.get("summary") or identity.identity_summary,
        "core_temperament": list(identity.core_temperament),
        "cognitive_style": list(identity.cognitive_style),
        "thinking_habits": list(identity.thinking_habits),
        "values": list(identity.value_orientation),
        "emotional_expression": list(identity.emotional_expression),
        "intimate_relationship": list(identity.intimate_relationship),
        "communication": communication,
        "natural_behavior": list(identity.natural_behavior),
        "misconceptions": list(identity.misconceptions),
    }


def _state(
    emotion_primary: str,
    emotion_cause: str,
    relationship_summary: str,
    interaction_mode: str,
    proactive_allowed: bool,
    interaction_energy: str = "normal",
    *,
    emotion_detail: dict[str, object] | None = None,
    relationship_detail: dict[str, object] | None = None,
) -> dict[str, object]:
    detail = emotion_detail or {}
    attachment = relationship_detail or {}
    raw_levels = detail.get("levels")
    levels = normalize_levels(raw_levels if isinstance(raw_levels, dict) else None)
    summary = detail.get("summary")
    if not isinstance(summary, dict):
        summary = levels_summary(levels)
    return {
        "emotion_primary": emotion_primary,
        "emotion_cause": emotion_cause,
        "emotion": {
            "jealousy": detail.get("jealousy", 0),
            "possessiveness": detail.get("possessiveness", 0),
            "emotional_tension": detail.get("emotional_tension", 0),
            "triggers": detail.get("triggers", []),
            "summary": summary,
            # 决策可见压缩强度；表达侧不得把数值念给用户。
            "active_levels": {
                key: value for key, value in levels.items() if value >= 15
            },
        },
        "relationship_summary": relationship_summary,
        "attachment_state": {
            "attachment_strength": attachment.get("attachment_strength", 0),
            "emotional_reliance": attachment.get("emotional_reliance", 0),
            "relationship_security": attachment.get("relationship_security", 0),
            "perceived_specialness": attachment.get("perceived_specialness", 0),
            "separation_sensitivity": attachment.get("separation_sensitivity", 0),
            "reassurance_satisfaction": attachment.get("reassurance_satisfaction", 0),
            "closeness_desire": attachment.get("closeness_desire", 0),
            "exclusivity_need": attachment.get("exclusivity_need", 0),
        },
        "interaction_mode": interaction_mode,
        "interaction_energy": interaction_energy,
        "proactive_allowed": proactive_allowed,
    }


def _query(immediate_facts: list[dict[str, str]], working_memory: dict[str, object] | None) -> str:
    parts = [item.get("content", "") for item in immediate_facts]
    if working_memory is not None:
        topic = working_memory.get("current_topic")
        summary = working_memory.get("summary")
        if isinstance(topic, str):
            parts.append(topic)
        if isinstance(summary, str):
            parts.append(summary)
    return " ".join(part for part in parts if part).strip()


def _realization_query(
    immediate_facts: list[dict[str, str]],
    suggestion: ModelDecisionSuggestion,
    working_memory: dict[str, object] | None,
) -> str:
    del working_memory
    base = _query(immediate_facts, None)
    topic = suggestion.topic.topic_id or ""
    motive = " ".join(
        [
            suggestion.self_motivation.interest,
            suggestion.self_motivation.viewpoint,
            suggestion.self_motivation.desire_to_express,
        ]
    )
    return " ".join(part for part in (base, topic, motive) if part).strip()


def _matching(items: list[str], query: str) -> list[str]:
    if _about_self(query):
        return list(items)
    return [item for item in items if topic_related(query, item)]


def _about_self(query: str) -> bool:
    return any(piece in query for piece in _SELF_QUERY)


def _split_memories(
    memories: list[dict[str, object]],
    query: str,
    *,
    include_unmatched: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    initial: list[dict[str, object]] = []
    acquired: list[dict[str, object]] = []
    for memory in memories:
        origin = str(memory.get("origin") or "")
        content = str(memory.get("content") or "")
        summary = memory.get("summary")
        summary_text = summary if isinstance(summary, str) else None
        if not include_unmatched and query and not topic_related(query, content, summary_text):
            continue
        target = initial if origin in _INITIAL_ORIGINS else acquired
        target.append(memory)
    return initial, acquired


def _working_summary(working_memory: dict[str, object] | None, query: str) -> dict[str, object] | None:
    if working_memory is None:
        return None
    summary = working_memory.get("summary")
    topic = working_memory.get("current_topic")
    summary_text = summary if isinstance(summary, str) else ""
    topic_text = topic if isinstance(topic, str) else ""
    if query and not topic_related(query, summary_text, topic_text):
        return None
    if not summary_text and not topic_text:
        return None
    return {"summary": summary_text or None, "current_topic": topic_text or None}


def _load_object(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("交流配置必须是非空对象")
    result: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise ValueError("交流配置的每一项都要有文字")
        result[key] = value.strip()
    return result
