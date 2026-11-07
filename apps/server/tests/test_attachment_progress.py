from datetime import UTC, datetime, timedelta

from app.modules.dialogue.domain.attachment_progress import (
    collect_attachment_evidence,
    plan_attachment_progress,
)
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.turn_state import plan_turn_state
from app.modules.persona.domain.archive import AttachmentDisposition, TendencyLevel
from app.modules.state.domain.enums import InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import EmotionState, InteractionState, MotivationState, RelationshipState


def _disposition(*, attachment: TendencyLevel, independence: TendencyLevel = TendencyLevel.MEDIUM) -> AttachmentDisposition:
    return AttachmentDisposition(
        attachment_tendency=attachment,
        emotional_dependency_tendency=attachment,
        exclusivity_tendency=TendencyLevel.MEDIUM,
        separation_sensitivity=attachment,
        reassurance_need=attachment,
        affection_expression=attachment,
        jealousy_tendency=TendencyLevel.MEDIUM,
        possessiveness_tendency=TendencyLevel.MEDIUM,
        independence_need=independence,
    )


def _relationship(**overrides: object) -> RelationshipState:
    values: dict[str, object] = {
        "closeness": 0.25,
        "trust": 0.25,
        "attachment": 0.25,
        "care": 0.25,
        "current_tension": 0.1,
        "attachment_strength": 0.0,
        "emotional_reliance": 0.0,
        "relationship_security": 0.0,
        "perceived_specialness": 0.0,
        "separation_sensitivity": 0.0,
        "reassurance_satisfaction": 0.0,
        "closeness_desire": 0.0,
        "exclusivity_need": 0.0,
        "summary": "状态初始化",
    }
    values.update(overrides)
    return RelationshipState.model_validate(values)


def _emotion() -> EmotionState:
    return EmotionState(
        primary="calm",
        secondary=[],
        intensity=0,
        valence=0,
        arousal=0,
        cause_summary="状态初始化",
        updated_at=datetime(2026, 11, 7, tzinfo=UTC),
    )


def test_casual_exchanges_grow_slowly_and_keep_legacy_scores() -> None:
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    current = _relationship()
    first = plan_attachment_progress(
        current,
        _emotion(),
        _disposition(attachment=TendencyLevel.MEDIUM),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.RESPOND,
            self_motivation_kind=SelfMotivationKind.NONE,
            relationship_motivation_kind=None,
            user_message="今天天气不错",
            last_user_response_at=None,
            now=now,
        ),
        fallback=False,
    )
    assert first.relationship is not None
    assert first.relationship.closeness == 0.25
    assert first.relationship.attachment == 0.25
    assert 0 < first.relationship.attachment_strength < 0.03
    assert first.relationship.summary.startswith("初识")

    many = first.relationship
    for _ in range(20):
        step = plan_attachment_progress(
            many,
            _emotion(),
            _disposition(attachment=TendencyLevel.MEDIUM),
            collect_attachment_evidence(
                user_spoke=True,
                should_send=True,
                action=DialogueAction.RESPOND,
                self_motivation_kind=SelfMotivationKind.NONE,
                relationship_motivation_kind=None,
                user_message="随便聊聊",
                last_user_response_at=now,
                now=now,
            ),
            fallback=False,
        )
        assert step.relationship is not None
        many = step.relationship
    # 普通闲聊不应靠次数冲到亲密阶段。
    assert many.attachment_strength < 0.35


def test_intimate_signal_matters_more_than_small_talk() -> None:
    now = datetime(2026, 11, 7, 13, tzinfo=UTC)
    base = _relationship(attachment_strength=0.1, summary="初识阶段：有交流兴趣，依恋尚弱")
    casual = plan_attachment_progress(
        base,
        _emotion(),
        _disposition(attachment=TendencyLevel.HIGH),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.RESPOND,
            self_motivation_kind=SelfMotivationKind.NONE,
            relationship_motivation_kind=None,
            user_message="吃了吗",
            last_user_response_at=now - timedelta(minutes=5),
            now=now,
        ),
        fallback=False,
    )
    intimate = plan_attachment_progress(
        base,
        _emotion(),
        _disposition(attachment=TendencyLevel.HIGH),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.REACT,
            self_motivation_kind=SelfMotivationKind.EXPRESS_EMOTION,
            relationship_motivation_kind=SelfMotivationKind.SEEK_CONNECTION,
            user_message="我好想你",
            last_user_response_at=now - timedelta(minutes=5),
            now=now,
        ),
        fallback=False,
    )
    assert casual.relationship is not None
    assert intimate.relationship is not None
    assert intimate.relationship.attachment_strength > casual.relationship.attachment_strength + 0.02
    assert intimate.relationship.perceived_specialness > casual.relationship.perceived_specialness


def test_high_disposition_grows_faster_but_respects_space() -> None:
    now = datetime(2026, 11, 7, 14, tzinfo=UTC)
    base = _relationship(attachment_strength=0.2, closeness_desire=0.4)
    high = plan_attachment_progress(
        base,
        _emotion(),
        _disposition(attachment=TendencyLevel.HIGH),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.SHARE,
            self_motivation_kind=SelfMotivationKind.SHOW_CARE,
            relationship_motivation_kind=None,
            user_message="我喜欢你",
            last_user_response_at=now - timedelta(hours=1),
            now=now,
        ),
        fallback=False,
    )
    low = plan_attachment_progress(
        base,
        _emotion(),
        _disposition(attachment=TendencyLevel.LOW, independence=TendencyLevel.HIGH),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.SHARE,
            self_motivation_kind=SelfMotivationKind.SHOW_CARE,
            relationship_motivation_kind=None,
            user_message="我喜欢你",
            last_user_response_at=now - timedelta(hours=1),
            now=now,
        ),
        fallback=False,
    )
    assert high.relationship is not None
    assert low.relationship is not None
    assert high.relationship.attachment_strength > low.relationship.attachment_strength

    spaced = plan_attachment_progress(
        high.relationship,
        _emotion(),
        _disposition(attachment=TendencyLevel.HIGH),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.RESPOND,
            self_motivation_kind=SelfMotivationKind.NONE,
            relationship_motivation_kind=None,
            user_message="我今天想独处，别打扰",
            last_user_response_at=now - timedelta(minutes=3),
            now=now,
        ),
        fallback=False,
    )
    assert spaced.relationship is not None
    assert spaced.relationship.closeness_desire < high.relationship.closeness_desire
    assert spaced.relationship.attachment_strength == high.relationship.attachment_strength
    assert spaced.relationship.exclusivity_need <= high.relationship.exclusivity_need


def test_rival_mention_raises_noticeable_but_bounded_jealousy() -> None:
    now = datetime(2026, 11, 7, 16, tzinfo=UTC)
    progress = plan_attachment_progress(
        _relationship(attachment_strength=0.3, exclusivity_need=0.15),
        _emotion(),
        _disposition(attachment=TendencyLevel.MEDIUM),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.RESPOND,
            self_motivation_kind=SelfMotivationKind.NONE,
            relationship_motivation_kind=None,
            user_message="今天和一个异性朋友单独出去玩了，聊得挺开心的。",
            last_user_response_at=now - timedelta(minutes=8),
            now=now,
        ),
        fallback=False,
    )
    assert progress.emotion is not None
    assert progress.emotion.jealousy >= 0.18
    assert progress.emotion.jealousy <= 0.35
    assert progress.emotion.levels["jealousy"] >= 18


def test_mutual_exchange_grows_reliance_with_dependency_tendency() -> None:
    now = datetime(2026, 11, 7, 17, tzinfo=UTC)
    base = _relationship(attachment_strength=0.12, emotional_reliance=0.0)
    high_dep = AttachmentDisposition(
        attachment_tendency=TendencyLevel.MEDIUM,
        emotional_dependency_tendency=TendencyLevel.HIGH,
        exclusivity_tendency=TendencyLevel.MEDIUM,
        separation_sensitivity=TendencyLevel.MEDIUM,
        reassurance_need=TendencyLevel.HIGH,
        affection_expression=TendencyLevel.MEDIUM,
        jealousy_tendency=TendencyLevel.MEDIUM,
        possessiveness_tendency=TendencyLevel.MEDIUM,
        independence_need=TendencyLevel.LOW,
    )
    low_dep = AttachmentDisposition(
        attachment_tendency=TendencyLevel.MEDIUM,
        emotional_dependency_tendency=TendencyLevel.LOW,
        exclusivity_tendency=TendencyLevel.MEDIUM,
        separation_sensitivity=TendencyLevel.MEDIUM,
        reassurance_need=TendencyLevel.LOW,
        affection_expression=TendencyLevel.MEDIUM,
        jealousy_tendency=TendencyLevel.MEDIUM,
        possessiveness_tendency=TendencyLevel.MEDIUM,
        independence_need=TendencyLevel.HIGH,
    )
    evidence = collect_attachment_evidence(
        user_spoke=True,
        should_send=True,
        action=DialogueAction.RESPOND,
        self_motivation_kind=SelfMotivationKind.NONE,
        relationship_motivation_kind=None,
        user_message="今天天气不错",
        last_user_response_at=now - timedelta(minutes=4),
        now=now,
    )
    high = plan_attachment_progress(base, _emotion(), high_dep, evidence, fallback=False)
    low = plan_attachment_progress(base, _emotion(), low_dep, evidence, fallback=False)
    assert high.relationship is not None and low.relationship is not None
    assert high.relationship.emotional_reliance > low.relationship.emotional_reliance


def test_gap_raises_desire_without_inventing_attachment_strength() -> None:
    now = datetime(2026, 11, 7, 18, tzinfo=UTC)
    base = _relationship(attachment_strength=0.22, summary="熟悉阶段：开始形成共同交流期待")
    progress = plan_attachment_progress(
        base,
        _emotion(),
        _disposition(attachment=TendencyLevel.HIGH),
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.RESPOND,
            self_motivation_kind=SelfMotivationKind.NONE,
            relationship_motivation_kind=None,
            user_message="我回来了",
            last_user_response_at=now - timedelta(hours=40),
            now=now,
        ),
        fallback=False,
    )
    assert progress.relationship is not None
    assert progress.relationship.closeness_desire > base.closeness_desire
    assert progress.relationship.attachment_strength >= base.attachment_strength
    assert progress.emotion is not None
    assert "久未联系" in progress.emotion.triggers


def test_turn_state_records_attachment_evidence_in_reason() -> None:
    now = datetime(2026, 11, 7, 19, tzinfo=UTC)
    plan = plan_turn_state(
        action=DialogueAction.REACT,
        secondary_actions=[],
        should_send=True,
        fallback=False,
        blocked=False,
        confidence=0.6,
        emotion=_emotion(),
        relationship=_relationship(),
        interaction=InteractionState(
            mode=InteractionMode.AVAILABLE,
            proactive_allowed=False,
            waiting_for_user=False,
            consecutive_unanswered_messages=0,
        ),
        motivation=MotivationState(
            primary=MotivationKind.REST,
            secondary=[],
            intensity=0,
            target=None,
            reason="状态初始化",
        ),
        user_spoke=True,
        now=now,
        disposition=_disposition(attachment=TendencyLevel.HIGH),
        self_motivation_kind=SelfMotivationKind.EXPRESS_EMOTION,
        user_message="我想你了",
    )
    assert plan is not None
    assert plan.relationship is not None
    assert plan.relationship.attachment_strength > 0
    assert "依据" in plan.reason
    assert plan.relationship.closeness == 0.25
