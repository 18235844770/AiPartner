import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.dialogue.domain.context_builder import decision_messages
from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind, TopicTransition
from app.modules.dialogue.domain.suggestion import (
    EmotionalMotivation,
    ModelDecisionSuggestion,
    RelationshipMotivation,
    SelfMotivation,
    UserNeed,
)
from app.modules.persona.domain.archive import TendencyLevel
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates
from app.modules.state.domain.snapshots import EmotionState, RelationshipState, initial_snapshots


def test_six_mbti_have_distinct_attachment_dispositions() -> None:
    templates = load_persona_templates()
    signatures = {
        mbti: template.archive.relationship.attachment_disposition.model_dump(mode="json")
        for mbti, template in templates.items()
    }
    assert len({tuple(sorted(item.items())) for item in signatures.values()}) >= 4
    assert templates[MbtiType.INFP].archive.relationship.attachment_disposition.affection_expression == TendencyLevel.HIGH
    assert templates[MbtiType.INTJ].archive.relationship.attachment_disposition.independence_need == TendencyLevel.HIGH
    assert all(not item.archive.self_model.human_identity for item in templates.values())


def test_initial_attachment_state_starts_low_not_from_disposition() -> None:
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    relationship = initial_snapshots(now)["relationship"]
    assert isinstance(relationship, RelationshipState)
    assert relationship.attachment_strength == 0
    assert relationship.emotional_reliance == 0
    assert relationship.closeness_desire == 0
    emotion = initial_snapshots(now)["emotion"]
    assert isinstance(emotion, EmotionState)
    assert emotion.jealousy == 0
    assert emotion.possessiveness == 0


def test_decision_context_exposes_self_model_and_attachment_layers() -> None:
    archive = load_persona_templates()[MbtiType.INFP].archive.dump()
    messages = decision_messages(
        mbti_type="INFP",
        core_traits={"title": "理想型"},
        communication_preferences={"summary": "细腻"},
        emotion_primary="longing",
        emotion_cause="交流变少",
        relationship_summary="已经开始交流",
        interaction_mode="available",
        proactive_allowed=True,
        recent_messages=[],
        repair=False,
        archive=archive,
        emotion_detail={
            "jealousy": 0.1,
            "possessiveness": 0.2,
            "emotional_tension": 0.3,
            "triggers": ["久未联系"],
        },
        relationship_detail={
            "attachment_strength": 0.4,
            "emotional_reliance": 0.3,
            "relationship_security": 0.5,
            "perceived_specialness": 0.4,
            "separation_sensitivity": 0.6,
            "reassurance_satisfaction": 0.2,
            "closeness_desire": 0.7,
            "exclusivity_need": 0.3,
        },
    )
    body = json.loads(messages[1].content)
    assert body["self_model"]["human_identity"] is False
    assert body["relationship_profile"]["attachment_disposition"]["attachment_tendency"] == "high"
    assert body["state"]["attachment_state"]["closeness_desire"] == 0.7
    assert body["state"]["emotion"]["triggers"] == ["久未联系"]
    assert "self_model" in messages[0].content
    assert "emotional_motivation" in messages[0].content
    assert "relationship_motivation" in messages[0].content


def test_relationship_motivation_is_optional_and_validated() -> None:
    suggestion = ModelDecisionSuggestion(
        should_send=True,
        primary_action=DialogueAction.REACT,
        motivation=DecisionMotivation(primary="表达在意"),
        user_need=UserNeed(summary="用户提起别人"),
        self_motivation=SelfMotivation(
            kind=SelfMotivationKind.EXPRESS_EMOTION,
            interest="关系里的特殊性",
            viewpoint="可以不舒服，但不能控制对方",
            desire_to_express="说一点不是滋味",
            source="relationship_state",
            reason="独占需求被碰到",
        ),
        emotional_motivation=EmotionalMotivation(emotion="jealousy", intensity=0.4),
        relationship_motivation=RelationshipMotivation(
            kind=SelfMotivationKind.SEEK_ATTENTION,
            intensity=0.5,
            reason="希望确认自己仍被重视",
        ),
        topic=DecisionTopic(transition=TopicTransition.CONTINUE),
        confidence=Decimal("0.6"),
        reasoning_summary="表达在意，不控制对方",
    )
    assert suggestion.relationship_motivation is not None
    assert suggestion.emotional_motivation is not None
    assert suggestion.emotional_motivation.emotion == "jealousy"
    with pytest.raises(ValidationError):
        EmotionalMotivation(emotion=" ", intensity=0.1)
