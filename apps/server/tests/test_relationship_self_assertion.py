"""Relationship Self-Assertion：参数、决策因子与冲突后情绪保留。"""

from datetime import UTC, datetime, timedelta

from app.modules.dialogue.domain.context_builder import decision_messages, realization_messages
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.relationship_assertion import (
    build_relationship_assertion,
    user_message_has_friction,
)
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion
from app.modules.dialogue.domain.turn_state import plan_turn_state
from app.modules.persona.domain.archive import (
    PersonaArchive,
    RelationshipSelfAssertion,
    TendencyLevel,
    forgiveness_half_life_multipliers,
)
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates
from app.modules.state.domain.emotion import decay_levels, default_levels, normalize_levels
from app.modules.state.domain.enums import InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import EmotionState, InteractionState, MotivationState, RelationshipState


def _emotion(**levels: float) -> EmotionState:
    base = default_levels()
    base.update(levels)
    return EmotionState(
        primary="平静",
        secondary=[],
        intensity=0.2,
        valence=0.4,
        arousal=0.3,
        cause_summary="测试",
        levels=base,
        updated_at=datetime(2026, 11, 7, tzinfo=UTC),
    )


def _relationship() -> RelationshipState:
    return RelationshipState(
        closeness=0.2,
        trust=0.2,
        attachment=0.2,
        care=0.2,
        current_tension=0.2,
        summary="测试关系",
        attachment_strength=0.2,
    )


def _interaction() -> InteractionState:
    return InteractionState(
        mode=InteractionMode.AVAILABLE,
        proactive_allowed=True,
        waiting_for_user=False,
        consecutive_unanswered_messages=0,
    )


def _motivation() -> MotivationState:
    return MotivationState(
        primary=MotivationKind.REST,
        secondary=[],
        intensity=0,
        target=None,
        reason="测试",
    )


def _suggestion(*, kind: SelfMotivationKind, action: DialogueAction = DialogueAction.RESPOND) -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion.model_validate(
        {
            "should_send": True,
            "primary_action": action.value,
            "secondary_actions": [],
            "motivation": {"primary": "表达立场", "summary": "不为迎合而软化"},
            "user_need": {"summary": "用户在否定我的感受"},
            "self_motivation": {
                "kind": kind.value,
                "interest": "没有",
                "viewpoint": "我的感受成立",
                "desire_to_express": "说清楚",
            },
            "topic": {"topic_id": "conflict", "transition": "continue"},
            "fact_check": {"has_conflict": False, "conflict_summary": None, "should_correct": False},
            "confidence": 0.8,
            "reasoning_summary": "坚持自己的关系立场",
        }
    )


def test_six_mbti_templates_include_self_assertion() -> None:
    templates = load_persona_templates()
    assert templates[MbtiType.ENFP].archive.relationship.self_assertion.assertiveness == TendencyLevel.HIGH
    assert templates[MbtiType.ENFP].archive.relationship.self_assertion.confrontation_tendency == TendencyLevel.HIGH
    assert templates[MbtiType.INFP].archive.relationship.self_assertion.resentment_tendency == TendencyLevel.HIGH
    assert templates[MbtiType.INTJ].archive.relationship.self_assertion.assertiveness == TendencyLevel.HIGH
    assert templates[MbtiType.INTJ].archive.relationship.self_assertion.forgiveness_tendency == TendencyLevel.LOW
    assert templates[MbtiType.INFJ].archive.relationship.self_assertion.confrontation_tendency == TendencyLevel.MEDIUM


def test_old_relationship_json_without_self_assertion_still_parses() -> None:
    archive = load_persona_templates()[MbtiType.ENFP].archive.dump()
    relationship = dict(archive["relationship"])  # type: ignore[arg-type, index]
    relationship.pop("self_assertion", None)
    archive["relationship"] = relationship
    parsed = PersonaArchive.model_validate(archive)
    assert parsed.relationship.self_assertion.assertiveness == TendencyLevel.MEDIUM
    assert parsed.relationship.self_assertion.forgiveness_tendency == TendencyLevel.MEDIUM


def test_user_denial_raises_stance_pressure_and_hint() -> None:
    assertion = RelationshipSelfAssertion(
        assertiveness=TendencyLevel.HIGH,
        resentment_tendency=TendencyLevel.HIGH,
        confrontation_tendency=TendencyLevel.HIGH,
        forgiveness_tendency=TendencyLevel.LOW,
    )
    calm = build_relationship_assertion(assertion, default_levels())
    hurt = build_relationship_assertion(assertion, {"hurt": 55, "anger": 40, "sadness": 30})
    assert hurt.stance_pressure > calm.stance_pressure
    assert hurt.confrontation_bias > calm.confrontation_bias
    assert hurt.intimacy_dampen > 0.3
    assert hurt.repair_openness < calm.repair_openness
    assert "坚持" in hurt.stance_hint or "否定" in hurt.stance_hint
    assert user_message_has_friction("你想多了，别矫情")


def test_decision_context_includes_relationship_assertion() -> None:
    archive = load_persona_templates()[MbtiType.ENFP].archive.dump()
    messages = decision_messages(
        mbti_type="ENFP",
        core_traits={"title": "艺"},
        communication_preferences={},
        emotion_primary="委屈",
        emotion_cause="被否定感受",
        relationship_summary="关系紧张",
        interaction_mode="available",
        proactive_allowed=True,
        recent_messages=[{"sender_type": "user", "content": "你想多了"}],
        repair=False,
        archive=archive,
        emotion_detail={"levels": {"hurt": 48, "anger": 30}},
    )
    body = messages[1].content
    assert "relationship_assertion" in body
    assert "stance_hint" in body
    assert "self_assertion" in body
    assert "relationship_self_assertion" in messages[0].content or "assert_stance" in messages[0].content


def test_dissatisfaction_motive_raises_anger_or_hurt_and_is_not_quiet() -> None:
    before = _emotion(anger=10, hurt=12)
    plan = plan_turn_state(
        action=DialogueAction.RESPOND,
        secondary_actions=[],
        should_send=True,
        fallback=False,
        blocked=False,
        confidence=0.8,
        emotion=before,
        relationship=_relationship(),
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=True,
        now=datetime(2026, 11, 7, 12, tzinfo=UTC),
        self_assertion=RelationshipSelfAssertion(
            assertiveness=TendencyLevel.HIGH,
            resentment_tendency=TendencyLevel.HIGH,
            confrontation_tendency=TendencyLevel.HIGH,
            forgiveness_tendency=TendencyLevel.LOW,
        ),
        self_motivation_kind=SelfMotivationKind.EXPRESS_GRIEVANCE,
        user_message="你又把我晾在一边",
    )
    assert plan is not None
    assert plan.emotion is not None
    levels = normalize_levels(plan.emotion.levels)
    assert levels["anger"] > before.levels["anger"] or levels["hurt"] > before.levels["hurt"]
    suggestion = _suggestion(kind=SelfMotivationKind.EXPRESS_GRIEVANCE)
    assert suggestion.should_send is True
    assert suggestion.primary_action != DialogueAction.QUIET
    assert suggestion.self_motivation.kind == SelfMotivationKind.EXPRESS_GRIEVANCE


def test_denied_feeling_keeps_assert_stance_motive() -> None:
    suggestion = ModelDecisionSuggestion.model_validate(
        {
            "should_send": True,
            "primary_action": "respond",
            "secondary_actions": ["react"],
            "motivation": {"primary": "坚持感受", "summary": "不立刻认错"},
            "user_need": {"summary": "用户否定我的感受"},
            "self_motivation": {
                "kind": "hold_position",
                "interest": "没有",
                "viewpoint": "我的感受不是矫情",
                "desire_to_express": "说清楚",
            },
            "relationship_motivation": {
                "kind": "assert",
                "intensity": "high",
                "reason": "立场不能立刻让步",
            },
            "topic": {"topic_id": "feelings", "transition": "continue"},
            "fact_check": {"has_conflict": False, "conflict_summary": None, "should_correct": False},
            "confidence": 0.75,
            "reasoning_summary": "用户否定感受，坚持立场",
        }
    )
    assert suggestion.self_motivation.kind == SelfMotivationKind.ASSERT_STANCE
    assert suggestion.relationship_motivation is not None
    assert suggestion.relationship_motivation.kind == SelfMotivationKind.ASSERT_STANCE
    factor = build_relationship_assertion(
        RelationshipSelfAssertion(assertiveness=TendencyLevel.HIGH),
        {"hurt": 50, "anger": 25},
    )
    assert factor.stance_pressure >= 0.55


def test_conflict_emotion_persists_into_next_ordinary_respond() -> None:
    conflicted = _emotion(anger=48, hurt=42, sadness=28)
    conflicted = conflicted.model_copy(update={"primary": "愤怒", "cause_summary": "上一轮冲突"})
    plan = plan_turn_state(
        action=DialogueAction.RESPOND,
        secondary_actions=[],
        should_send=True,
        fallback=False,
        blocked=False,
        confidence=0.7,
        emotion=conflicted,
        relationship=_relationship(),
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=True,
        now=datetime(2026, 11, 7, 13, tzinfo=UTC),
        self_assertion=RelationshipSelfAssertion(forgiveness_tendency=TendencyLevel.LOW),
        self_motivation_kind=SelfMotivationKind.NONE,
        user_message="那我们换个话题吧",
    )
    assert plan is not None
    assert plan.emotion is not None
    levels = normalize_levels(plan.emotion.levels)
    assert levels["anger"] >= 40
    assert levels["hurt"] >= 35
    assert plan.emotion.primary not in {"平静", "专注"} or levels["anger"] >= 40


def test_forgiveness_speeds_anger_hurt_decay() -> None:
    levels = default_levels()
    levels["anger"] = 60
    levels["hurt"] = 60
    elapsed = timedelta(hours=12)
    slow = decay_levels(levels, elapsed, half_life_multipliers=forgiveness_half_life_multipliers(TendencyLevel.LOW))
    fast = decay_levels(levels, elapsed, half_life_multipliers=forgiveness_half_life_multipliers(TendencyLevel.HIGH))
    assert fast["anger"] < slow["anger"]
    assert fast["hurt"] < slow["hurt"]


def test_realization_includes_self_assertion() -> None:
    archive = load_persona_templates()[MbtiType.INTJ].archive.dump()
    messages = realization_messages(
        _suggestion(kind=SelfMotivationKind.ASSERT_STANCE),
        [{"sender_type": "user", "content": "你想多了"}],
        mbti_type="INTJ",
        core_traits={"title": "测"},
        communication_preferences={},
        emotion_primary="愤怒",
        emotion_cause="被否定",
        relationship_summary="紧张",
        interaction_mode="available",
        proactive_allowed=True,
        archive=archive,
        emotion_detail={"levels": {"anger": 40, "hurt": 30}},
    )
    body = messages[1].content
    assert "self_assertion" in body
    assert "relationship_assertion" in body
