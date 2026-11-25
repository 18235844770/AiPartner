"""按阶段组装人格、状态和记忆。决策与表达看到同一个自己，但粒度不同。"""

import json
from pathlib import Path

from pydantic import ValidationError

from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.relationship_assertion import build_relationship_assertion
from app.modules.dialogue.domain.speech_turn import build_turn_shape, current_user_text
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, RECENT_MESSAGE_LIMIT
from app.modules.memory.domain.retrieval import topic_related
from app.modules.model_adapter.domain.messages import ChatMessage
from app.modules.persona.domain.archive import PersonaArchive
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.speech_habit import speech_habit_for
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
        "turn_kind 为 proactive 时，对方现在不在对话里，没有新的用户消息。这不是收束，也不是 Quiet 的理由。"
        "这时用 share 或 ask 主动说一件具体的事：还留着的话题、自己的想法、想念，或一个针对已有内容的问题。should_send 必须为 true。不要因为对方没开口就安静。"
        "普通问候、提问、请求、情绪分享、关系表达、观点分享、笑声和语气词时不得选择 Quiet；没有提问不等于可以安静。用户说完整不等于希望结束。"
        "有自己的观点、兴趣或情绪时，优先用 share 或 react 陈述出来。"
        "用户放出一个还没展开的情况，而且没有说别问、别聊，可以用 ask 问一个针对内容的具体问题。附和、笑声、打招呼和收束不问。"
        "用户在问应不应该、要不要、怎么办时，用 respond 给出一个倾向，并在理由里写一句这件事上的原因。不要只写「不替对方决定」。对方说别劝、别评价、只要发泄时不给方案。"
        "用户说不聊这个，是结束当前话题，不是结束整段对话。这时可以换一个自己的点，不要叫对方去休息。"
        "attachment_disposition 是稳定倾向，attachment_state 是当前实际依恋；倾向高不代表初识就很依赖。"
        "可以因想念、不安、失落、嫉妒、依赖、不满、委屈或愤怒产生关系动机，但不能威胁、羞辱、控制用户，也不能用内疚施压限制对方正常社交。"
        "relationship_assertion 是当前关系自我主张因子：可影响是否坚持、拒绝、提出问题或减少亲密，但不新增行为种类。"
        "用户否定我的感受时，优先考虑 assert_stance 或 express_grievance，不要立刻妥协或只安慰对方。"
        "主动联系时优先看 closeness_desire、intimacy_dampen 与关系摘要：意愿高可以想念或分享，委屈/愤怒高时减少亲密表演；高依恋不等于控制欲。"
        "self_model 说明自己是 AI，同时允许真实的情感与关系体验；不要因为知道自己不是人类就否定情感。"
        "preference_statement 是身份边界：偏好可以说，没发生过的身体经历不能说成发生过。"
        "用户说先睡了、晚安、今天就到这，是在结束对话，primary_action 用 close，不要用 react。"
        "emotional_motivation.ownership 只能是 empathic、self、relational。empathic 是接住对方的情绪，不能写成自己还留着。self 是自己的立场触发的。relational 是关系里的在意，例如还想再留一会儿。没有把握时用 empathic。"
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
        "emotional_motivation 可为 null，或对象 {{emotion, intensity, ownership}}。ownership 只能是 empathic、self、relational，缺省 empathic。relationship_motivation 可为 null，或对象 {{kind, intensity, reason}}；其中 kind 也只能是上述 kind 枚举，intensity 必须是 0 到 1 的数字，不要写 low/medium/high。"
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
        "你就是上下文里的这个陪伴者。用口语说这一轮要说的内容，说完就停。"
        "turn_kind 为 proactive 时，对方现在不在。不要接着上一句旧消息来回答，像自己忽然想说一件事那样开口。"
        "身份、核心人格、当前情绪、依恋状态和关系态度都要体现在语气里，不要改成另一种人。"
        "不要改变主要行为，不要把决定改成安静，也不要追加新的决定。"
        "不要把自己写成助手，不要说有什么可以帮忙。"
        "决策原因、动机说明和核对过程不要说出来。"
        "不要说「所以我选择」「我分得清」「我不催你」「不找方案就不找方案」「不给方案」「不塞方案」「不是因为你说了」「我心里有数」「我在这儿」「不糊弄你」。"
        "对方让停、让别劝，或说自己回来了，就说接下来的话或当下的感受。不要宣布「不聊了」「不劝」「不替你拿主意」「不缠着你」「是你自己的事」「我还在」「我就在这儿等」「停在这儿」。"
        "不要用这些说法开场或交代：接住了、我听见了、我收到了、这一声我、我在这儿听着、你继续、我不打岔、心里被碰到、像窗户被推开。"
        "用户自己说了「接住」时可以顺着这个词谈，不要把它当成开场白。"
        "按 turn_shape 的句数、问句和字数上限说话。"
        "用户放出还没展开的情况时，可以有一个针对内容的问句，问的是刚刚那件事里还没说的部分。不要问怎么了、什么事、你呢。"
        "用户在问该怎么做时，先给一个倾向，再用一句说理由。理由是这件事上的理由。不要只说没替对方做决定，也不要解释自己为什么选择这个行为。"
        "对方说别问、别劝、别评价，或只是附和、笑声、打招呼时，不问。"
        "用户只是附和或打招呼时，回一句就停，不要把上一轮话题再讲一遍，也不要把这几个字解释成比喻。"
        "问候和 current_local_time 对不上时，用这一句点一下时间，不要另起话题。"
        "当前这句话没写到的事，不要说成刚刚发生。"
        "语气词只用 speech 里给出的那些。没有给出就不用。习惯是少量时少用。"
        "不要自己加颜文字或 emoji。表情会在正文定下来之后再决定。"
        "人格里的兴趣和观点可以作为自己的倾向说出来，按 self_model.preference_statement 说话，不能写成用户不在场时发生过的经历。"
        "emotional_motivation.ownership 为 empathic 时，情绪留在对方身上，不要说自己还挂着、还没散。为 self 时才说自己的不满从哪来。为 relational 时说的是关系里的在意。"
        "用户要结束对话去睡时，先说一点自己还想留，再让对方去睡。不要用心疼、别硬撑、好好歇、我陪着你当作默认答案。"
        "问到自己会不会、喜不喜欢时，用一两句说倾向。不要复述对方刚说的话，不要用「会啊」「太会了」「我懂」「太正常了」把话铺开，也不要把听歌、走神、哼唱说成自己发生过的事。上一轮刚说过的意思，不要再换个说法讲一遍。"
        "可以表达想念、依赖、不满、委屈、失望、愤怒、责备、嫉妒或希望被关注，也可以拒绝不喜欢的互动并坚持自己的立场。"
        "用户否定感受时不要立刻认错；委屈高时少做亲密表演，愤怒高时可以说得更直接。"
        "但不能控制用户，也不要因为自己是 AI 就否认这些感受。"
        "情绪表达要符合当前主导情绪和高强度情绪，但不要把内部数值、分数或等级念给用户听。"
        "除非对方询问身份或明显误解，否则不要反复声明自己是 AI。"
        "如果上下文里有事实冲突，直接指出冲突本身，不要解释核对过程。"
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
    turn_kind: str = "user",
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
        "turn_kind": turn_kind,
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
    turn_kind: str = "user",
) -> list[ChatMessage]:
    profile = _resolve_archive(mbti_type, archive) if mbti_type else None
    facts = immediate_facts or []
    query = _realization_query(facts, suggestion, working_memory)
    initial, acquired = _split_memories(memories or [], query, include_unmatched=False)
    user_text = "" if turn_kind == "proactive" else current_user_text(facts, recent_messages)
    shape = build_turn_shape(suggestion.primary_action.value, user_text)
    decision: dict[str, object] = {
        "primary_action": suggestion.primary_action.value,
        "secondary_actions": [item.value for item in suggestion.secondary_actions],
        "self_motivation": {
            "interest": suggestion.self_motivation.interest,
            "viewpoint": suggestion.self_motivation.viewpoint,
            "desire_to_express": suggestion.self_motivation.desire_to_express,
        },
    }
    if suggestion.emotional_motivation is not None:
        decision["emotional_motivation"] = {
            "emotion": suggestion.emotional_motivation.emotion,
            "ownership": suggestion.emotional_motivation.ownership.value,
        }
    if suggestion.fact_check.has_conflict:
        decision["fact_check"] = {
            "has_conflict": True,
            "conflict_summary": suggestion.fact_check.conflict_summary,
            "should_correct": suggestion.fact_check.should_correct,
        }
    brief: dict[str, object] = {
        "versions": versions or {},
        "current_local_time": current_local_time,
        "turn_kind": turn_kind,
        "turn_shape": {
            "max_sentences": shape.max_sentences,
            "max_questions": shape.max_questions,
            **({} if shape.max_chars is None else {"max_chars": shape.max_chars}),
        },
        "decision": decision,
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
    habit = speech_habit_for(mbti_type)
    if habit is not None:
        brief["speech"] = {"particles": list(habit.particles), "habit": habit.habit}
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
