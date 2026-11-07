import pytest
from pydantic import ValidationError

from app.modules.dialogue.domain.enums import SelfMotivationKind
from app.modules.dialogue.domain.suggestion import FactCheckResult, SelfMotivation
from app.modules.dialogue.domain.turn_state import plan_turn_state
from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.state.domain.enums import InteractionEnergy, InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import EmotionState, InteractionState, MotivationState, RelationshipState, initial_snapshots
from datetime import UTC, datetime


def test_self_motivation_kind_defaults_to_none() -> None:
    motivation = SelfMotivation(
        interest="没有",
        viewpoint="没有",
        desire_to_express="先接住",
    )
    assert motivation.kind == SelfMotivationKind.NONE
    assert SelfMotivation.model_validate(
        {
            "kind": None,
            "interest": "故事",
            "viewpoint": "想分享",
            "desire_to_express": "说一句",
        }
    ).kind == SelfMotivationKind.NONE


def test_fact_check_requires_summary_when_conflict_exists() -> None:
    assert FactCheckResult().has_conflict is False
    with pytest.raises(ValidationError):
        FactCheckResult(has_conflict=True, should_correct=True)
    with pytest.raises(ValidationError):
        FactCheckResult(has_conflict=True, conflict_summary="现在是晚上", should_correct=False)
    with pytest.raises(ValidationError):
        FactCheckResult(has_conflict=False, conflict_summary="多余", should_correct=False)
    checked = FactCheckResult(has_conflict=True, conflict_summary="现在是晚上，不是早上好", should_correct=True)
    assert checked.should_correct is True


def test_interaction_energy_defaults_to_normal_and_not_quiet() -> None:
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    snapshots = initial_snapshots(now)
    interaction = snapshots["interaction"]
    assert isinstance(interaction, InteractionState)
    assert interaction.energy == InteractionEnergy.NORMAL
    assert interaction.energy != InteractionEnergy.QUIET
    loaded = InteractionState.model_validate(
        {
            "mode": "available",
            "proactive_allowed": False,
            "waiting_for_user": False,
            "consecutive_unanswered_messages": 0,
        }
    )
    assert loaded.energy == InteractionEnergy.NORMAL


def test_user_return_lifts_quiet_energy_without_changing_relationship_scores() -> None:
    now = datetime(2026, 11, 7, 14, tzinfo=UTC)
    plan = plan_turn_state(
        action=DialogueAction.RESPOND,
        secondary_actions=[],
        should_send=True,
        fallback=False,
        blocked=False,
        confidence=0.5,
        emotion=EmotionState(
            primary="calm",
            secondary=[],
            intensity=0,
            valence=0,
            arousal=0,
            cause_summary="状态初始化",
            updated_at=now,
        ),
        relationship=RelationshipState(
            closeness=0.25,
            trust=0.25,
            attachment=0.25,
            care=0.25,
            current_tension=0,
            summary="已经开始交流，关系程度仍保持原来的判断",
        ),
        interaction=InteractionState(
            mode=InteractionMode.AVAILABLE,
            proactive_allowed=True,
            waiting_for_user=False,
            energy=InteractionEnergy.QUIET,
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
    )
    assert plan is not None
    assert plan.interaction is not None
    assert plan.interaction.energy == InteractionEnergy.NORMAL
    assert plan.relationship is not None
    assert plan.relationship.closeness == 0.25
    assert plan.relationship.trust == 0.25
    assert plan.relationship.attachment == 0.25
    assert plan.relationship.care == 0.25
