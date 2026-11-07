import json

import pytest
from pydantic import ValidationError

from app.modules.dialogue.domain.context_builder import decision_messages, realization_messages
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition
from app.modules.dialogue.domain.suggestion import (
    ModelDecisionSuggestion,
    SelfMotivation,
    UserNeed,
    assistant_self_reference,
)
from app.modules.infrastructure.domain.log_capture import omit_text, redact_secrets
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates


def test_missing_self_motivation_is_recorded_as_none_without_another_call() -> None:
    suggestion = ModelDecisionSuggestion.model_validate(
        {
            "should_send": True,
            "primary_action": "respond",
            "secondary_actions": [],
            "motivation": {"primary": "回应当前内容"},
            "user_need": {"summary": "用户在纠正一个说法"},
            "self_motivation": {"interest": None, "viewpoint": None, "desire_to_express": "接住这个纠正"},
            "topic": {"transition": "continue"},
            "confidence": "0.5",
            "reasoning_summary": "先承认说错的部分",
        }
    )
    assert suggestion.self_motivation.interest == "没有"
    assert suggestion.self_motivation.viewpoint == "没有"


def test_assistant_label_is_rejected_and_a_denial_is_kept() -> None:
    assert assistant_self_reference("助手应先共情")
    assert not assistant_self_reference("我不是助手，这句不必接")
    with pytest.raises(ValidationError):
        _suggestion("助手坦诚分享自己的观影偏好")


def test_decision_context_keeps_identity_and_selects_related_interests() -> None:
    archive = load_persona_templates()[MbtiType.ENFP].archive.dump()
    messages = decision_messages(
        mbti_type="ENFP",
        core_traits={"title": "探索型", "summary": "外向、好奇、热情。"},
        communication_preferences={"summary": "主动分享"},
        emotion_primary="calm",
        emotion_cause="状态初始化",
        relationship_summary="状态初始化",
        interaction_mode="available",
        proactive_allowed=True,
        recent_messages=[],
        repair=False,
        immediate_facts=[{"content": "你平时会喜欢故事吗？", "source": "current_message"}],
        archive=archive,
        versions={"persona_version_id": "persona-1", "state_version": "1"},
        memories=[
            {"origin": "user_explicit", "content": "今天下午看了一个故事", "is_inference": False},
            {"origin": "system_generated", "content": "初始时就关注故事", "is_inference": False},
            {"origin": "user_explicit", "content": "完全无关的采购清单", "is_inference": False},
        ],
    )
    body = json.loads(messages[1].content)
    assert "热情" in body["identity"]["definition"] or "好奇" in body["identity"]["definition"]
    assert "陪伴者" in body["identity"]["background"]
    assert body["identity"]["narrative"]
    assert body["core_persona"]["mbti_type"] == "ENFP"
    assert body["core_persona"]["core_temperament"]
    assert body["core_persona"]["misconceptions"]
    assert body["state"]["emotion_primary"] == "calm"
    assert body["state"]["interaction_energy"] == "normal"
    assert body["state"]["attachment_state"]["attachment_strength"] == 0
    assert body["self_model"]["human_identity"] is False
    assert body["relationship_profile"]["attachment_disposition"]
    assert any("故事" in item for item in body["interests"])
    assert body["versions"]["persona_version_id"] == "persona-1"
    assert any(item["origin"] == "system_generated" for item in body["initial_memories"])
    assert any("故事" in item["content"] for item in body["acquired_memories"])
    assert "Dialogue Policy" in messages[0].content
    assert "self_motivation" in messages[0].content
    assert "fact_check" in messages[0].content
    assert "share_interest" in messages[0].content
    assert "attachment_disposition" in messages[0].content


def test_realization_receives_identity_and_only_related_material() -> None:
    archive = load_persona_templates()[MbtiType.INTJ].archive.dump()
    messages = realization_messages(
        _suggestion("先说明自己的判断"),
        [],
        memories=[{"origin": "user_explicit", "content": "用户在问方向", "is_inference": False}],
        immediate_facts=[{"content": "这个长期方向你怎么看", "source": "current_message"}],
        mbti_type="INTJ",
        core_traits={"title": "战略型", "summary": "独立、目标导向、结构化。"},
        communication_preferences={"summary": "表达直接"},
        emotion_primary="calm",
        emotion_cause="状态初始化",
        relationship_summary="状态初始化",
        interaction_mode="available",
        proactive_allowed=False,
        working_memory={"summary": "还在谈长期方向", "current_topic": "长期方向", "open_threads": [{"title": "很长"}]},
        archive=archive,
        versions={"persona_version_id": "persona-2"},
    )
    body = json.loads(messages[1].content)
    assert body["identity"]["definition"]
    assert body["core_persona"]["values"]
    assert body["state"]["relationship_summary"] == "状态初始化"
    assert body["decision"]["self_motivation"]["desire_to_express"] == "先说明自己的判断"
    assert body["working_memory"] == {"summary": "还在谈长期方向", "current_topic": "长期方向"}
    assert "open_threads" not in body["working_memory"]
    unrelated = realization_messages(
        ModelDecisionSuggestion(
            should_send=True,
            primary_action=DialogueAction.RESPOND,
            motivation=DecisionMotivation(primary="回应当前内容"),
            user_need=UserNeed(summary="用户说吃过饭了"),
            self_motivation=SelfMotivation(
                interest="没有要接上的兴趣",
                viewpoint="这句不必展开",
                desire_to_express="没有要补充的",
            ),
            topic=DecisionTopic(transition=TopicTransition.NONE),
            confidence="0.5",
            reasoning_summary="这一轮没有新的判断",
        ),
        [],
        mbti_type="INTJ",
        archive=archive,
        immediate_facts=[{"content": "今天吃饭了", "source": "current_message"}],
        working_memory={"summary": "还在谈长期方向", "current_topic": "长期方向"},
    )
    omitted = json.loads(unrelated[1].content)
    assert "interests" not in omitted
    assert "working_memory" not in omitted
    assert omitted["identity"]["background"]


def test_snapshots_remove_secrets_and_can_omit_private_text() -> None:
    redacted = redact_secrets(
        {
            "messages": [{"role": "system", "content": "key sk-abcdefghijklmnopqrstuvwxyz"}],
            "api_key": "secret-value",
        }
    )
    assert isinstance(redacted, dict)
    assert redacted["api_key"] == "[redacted]"
    assert "sk-" not in str(redacted["messages"])
    hidden = omit_text({"messages": [{"content": "用户的原话"}], "model": "deepseek-flash"})
    assert hidden == {"messages": [{"content": "[omitted:5]"}], "model": "deepseek-flash"}


def _suggestion(desire: str) -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=True,
        primary_action=DialogueAction.RESPOND,
        motivation=DecisionMotivation(primary="回应当前内容"),
        user_need=UserNeed(summary="用户在询问看法"),
        self_motivation=SelfMotivation(
            interest="和长期方向有关",
            viewpoint="先给出自己的判断",
            desire_to_express=desire,
        ),
        topic=DecisionTopic(topic_id="direction", transition=TopicTransition.CONTINUE),
        confidence="0.5",
        reasoning_summary="这一轮有自己的判断",
    )
