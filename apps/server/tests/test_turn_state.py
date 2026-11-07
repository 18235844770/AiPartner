from datetime import UTC, datetime
from decimal import Decimal

from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.dialogue.domain.turn_state import plan_turn_state
from app.modules.state.domain.enums import InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import EmotionState, InteractionState, MotivationState, RelationshipState


def _emotion() -> EmotionState:
    return EmotionState(
        primary="calm",
        secondary=[],
        intensity=0,
        valence=0,
        arousal=0,
        cause_summary="状态初始化",
        updated_at=datetime(2026, 11, 6, tzinfo=UTC),
    )


def _relationship(summary: str = "状态初始化") -> RelationshipState:
    return RelationshipState(
        closeness=0.25,
        trust=0.25,
        attachment=0.25,
        care=0.25,
        current_tension=0.25,
        summary=summary,
    )


def _interaction(mode: InteractionMode = InteractionMode.AVAILABLE) -> InteractionState:
    return InteractionState(
        mode=mode,
        proactive_allowed=False,
        waiting_for_user=False,
        consecutive_unanswered_messages=0,
    )


def _motivation() -> MotivationState:
    return MotivationState(primary=MotivationKind.REST, secondary=[], intensity=0, target=None, reason="状态初始化")


def test_reply_updates_emotion_interaction_and_motivation_without_changing_scores() -> None:
    now = datetime(2026, 11, 6, 14, tzinfo=UTC)
    plan = plan_turn_state(
        action=DialogueAction.RESPOND,
        secondary_actions=[DialogueAction.REACT],
        should_send=True,
        fallback=False,
        blocked=False,
        confidence=float(Decimal("0.500")),
        emotion=_emotion(),
        relationship=_relationship(),
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=True,
        now=now,
        user_message="今天想和你聊聊近况",
    )
    assert plan is not None
    assert plan.emotion is not None
    assert plan.emotion.primary == "attentive"
    assert plan.interaction is not None
    assert plan.interaction.last_user_response_at == now
    assert plan.interaction.last_companion_message_at == now
    assert plan.interaction.waiting_for_user is True
    assert plan.interaction.consecutive_unanswered_messages == 1
    assert plan.interaction.proactive_allowed is False
    assert plan.motivation is not None
    assert plan.motivation.primary == MotivationKind.LISTEN
    assert plan.motivation.secondary == [MotivationKind.CONNECT]
    assert plan.relationship is not None
    assert plan.relationship.closeness == 0.25
    assert plan.relationship.trust == 0.25
    assert plan.relationship.attachment == 0.25
    assert plan.relationship.attachment_strength > 0
    assert plan.relationship.summary.startswith("初识")


def test_later_turn_keeps_legacy_scores_while_attachment_can_move() -> None:
    now = datetime(2026, 11, 6, 15, tzinfo=UTC)
    relationship = _relationship("熟悉阶段：开始形成共同交流期待")
    relationship = relationship.model_copy(update={"attachment_strength": 0.2})
    first = plan_turn_state(
        action=DialogueAction.QUIET,
        secondary_actions=[],
        should_send=False,
        fallback=False,
        blocked=False,
        confidence=0.5,
        emotion=_emotion(),
        relationship=relationship,
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=True,
        now=now,
        user_message="先不聊了",
    )
    assert first is not None
    # Quiet 且未发送时，没有 mutual_exchange；若无其他证据可不改依恋。
    if first.relationship is not None:
        assert first.relationship.closeness == 0.25
        assert first.relationship.trust == 0.25


def test_fallback_records_the_exchange_without_an_emotion() -> None:
    plan = plan_turn_state(
        action=DialogueAction.RESPOND,
        secondary_actions=[],
        should_send=True,
        fallback=True,
        blocked=False,
        confidence=0,
        emotion=_emotion(),
        relationship=_relationship(),
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=True,
        now=datetime(2026, 11, 6, 16, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.emotion is None
    assert plan.motivation is None
    assert plan.interaction is not None
    assert plan.reason == "决策没有完成，只记录这次交流发生过"


def test_blocked_or_failed_proactive_check_writes_nothing() -> None:
    now = datetime(2026, 11, 6, 17, tzinfo=UTC)
    arguments = dict(
        action=DialogueAction.QUIET,
        secondary_actions=[],
        should_send=False,
        fallback=True,
        confidence=0,
        emotion=_emotion(),
        relationship=_relationship(),
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=False,
        now=now,
    )
    assert plan_turn_state(blocked=True, **arguments) is None
    assert plan_turn_state(blocked=False, **arguments) is None


def test_user_message_ends_a_quiet_period() -> None:
    plan = plan_turn_state(
        action=DialogueAction.QUIET,
        secondary_actions=[],
        should_send=False,
        fallback=False,
        blocked=False,
        confidence=0.4,
        emotion=_emotion(),
        relationship=_relationship("已经开始交流，关系程度仍保持原来的判断"),
        interaction=_interaction(InteractionMode.QUIET),
        motivation=_motivation(),
        user_spoke=True,
        now=datetime(2026, 11, 6, 18, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.interaction is not None
    assert plan.interaction.mode == InteractionMode.AVAILABLE
    assert plan.interaction.quiet_until is None


def test_proactive_send_counts_an_unanswered_message() -> None:
    plan = plan_turn_state(
        action=DialogueAction.SHARE,
        secondary_actions=[],
        should_send=True,
        fallback=False,
        blocked=False,
        confidence=0.5,
        emotion=_emotion(),
        relationship=_relationship("已经开始交流，关系程度仍保持原来的判断"),
        interaction=_interaction(),
        motivation=_motivation(),
        user_spoke=False,
        now=datetime(2026, 11, 6, 19, tzinfo=UTC),
    )
    assert plan is not None
    assert plan.interaction is not None
    assert plan.interaction.consecutive_unanswered_messages == 1
    assert plan.interaction.last_user_response_at is None
    assert plan.relationship is not None
    assert plan.relationship.closeness == 0.25
    assert plan.relationship.attachment_strength > 0
    assert plan.emotion is not None
    assert plan.emotion.primary == "engaged"
