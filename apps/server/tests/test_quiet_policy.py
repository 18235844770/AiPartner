from decimal import Decimal

from app.modules.dialogue.domain.decision import DecisionMotivation, DecisionTopic
from app.modules.dialogue.domain.enums import DialogueAction, TopicTransition
from app.modules.dialogue.domain.quiet_policy import (
    MAX_CONSECUTIVE_QUIET,
    apply_quiet_gate,
    requires_response,
    user_requests_silence,
)
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion, SelfMotivation, UserNeed


def _quiet() -> ModelDecisionSuggestion:
    return ModelDecisionSuggestion(
        should_send=False,
        primary_action=DialogueAction.QUIET,
        motivation=DecisionMotivation(primary="想安静"),
        user_need=UserNeed(summary="用户说完了"),
        self_motivation=SelfMotivation(
            interest="没有",
            viewpoint="没有",
            desire_to_express="不说",
        ),
        topic=DecisionTopic(transition=TopicTransition.NONE),
        confidence=Decimal("0.5"),
        reasoning_summary="模型建议 Quiet",
    )


def test_questions_and_greetings_require_response() -> None:
    assert requires_response("今天过得怎么样？")
    assert requires_response("你好")
    assert requires_response("我有点难过")
    assert requires_response("帮我听听这件事")
    assert not requires_response("我先安静一会儿")
    assert user_requests_silence("先别回我")


def test_question_cannot_stay_quiet() -> None:
    suggestion, meta = apply_quiet_gate(
        _quiet(),
        user_message="你怎么看这件事？",
        consecutive_quiet=0,
        user_triggered=True,
    )
    assert suggestion.primary_action == DialogueAction.RESPOND
    assert suggestion.should_send is True
    assert meta["quiet_gate"] == "forced_requires_response"


def test_consecutive_quiet_is_blocked() -> None:
    suggestion, meta = apply_quiet_gate(
        _quiet(),
        user_message="嗯",
        consecutive_quiet=MAX_CONSECUTIVE_QUIET,
        user_triggered=True,
    )
    assert suggestion.primary_action == DialogueAction.RESPOND
    assert meta["quiet_gate"] == "forced_consecutive_quiet"


def test_explicit_silence_request_allows_quiet() -> None:
    suggestion, meta = apply_quiet_gate(
        _quiet(),
        user_message="我先安静一会儿，先别回",
        consecutive_quiet=3,
        user_triggered=True,
    )
    assert suggestion.primary_action == DialogueAction.QUIET
    assert suggestion.should_send is False
    assert meta["quiet_gate"] == "allowed_silence_request"


def test_substantive_share_cannot_end_as_quiet() -> None:
    suggestion, meta = apply_quiet_gate(
        _quiet(),
        user_message="我觉得这部电影的结局其实在讲自我和解，而不是单纯的反转。",
        consecutive_quiet=0,
        user_triggered=True,
    )
    assert suggestion.primary_action == DialogueAction.RESPOND
    assert meta["quiet_gate"] == "forced_substantive_share"


def test_proactive_turns_are_not_forced() -> None:
    suggestion, meta = apply_quiet_gate(
        _quiet(),
        user_message=None,
        consecutive_quiet=5,
        user_triggered=False,
    )
    assert suggestion.primary_action == DialogueAction.QUIET
    assert meta == {}
