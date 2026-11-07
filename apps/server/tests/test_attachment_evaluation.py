"""六种人格的依恋对照评测：同样刺激，倾向不同，反应不同。"""

from datetime import UTC, datetime, timedelta

from app.modules.dialogue.domain.attachment_progress import (
    collect_attachment_evidence,
    plan_attachment_progress,
)
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.proactive import (
    EARLY_STAGE_USER_SILENCE,
    HIGH_DESIRE_USER_SILENCE,
    MEDIUM_DESIRE_USER_SILENCE,
    ProactiveAttachmentCue,
    ProactiveMessage,
    attachment_silence_block,
    required_user_silence,
)
from app.modules.persona.domain.archive import TendencyLevel
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates
from app.modules.state.domain.snapshots import EmotionState, RelationshipState


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


def _relationship(**overrides: object) -> RelationshipState:
    values: dict[str, object] = {
        "closeness": 0.2,
        "trust": 0.2,
        "attachment": 0.2,
        "care": 0.2,
        "current_tension": 0.1,
        "attachment_strength": 0.22,
        "emotional_reliance": 0.1,
        "relationship_security": 0.3,
        "perceived_specialness": 0.2,
        "separation_sensitivity": 0.2,
        "reassurance_satisfaction": 0.4,
        "closeness_desire": 0.2,
        "exclusivity_need": 0.1,
        "summary": "熟悉阶段：开始形成共同交流期待",
    }
    values.update(overrides)
    return RelationshipState.model_validate(values)


def _after_day_away(mbti: MbtiType) -> RelationshipState:
    now = datetime(2026, 11, 7, 20, tzinfo=UTC)
    template = load_persona_templates()[mbti]
    progress = plan_attachment_progress(
        _relationship(),
        _emotion(),
        template.archive.relationship.attachment_disposition,
        collect_attachment_evidence(
            user_spoke=True,
            should_send=True,
            action=DialogueAction.RESPOND,
            self_motivation_kind=SelfMotivationKind.NONE,
            relationship_motivation_kind=None,
            user_message="我回来了",
            last_user_response_at=now - timedelta(hours=26),
            now=now,
        ),
        fallback=False,
    )
    assert progress.relationship is not None
    return progress.relationship


def test_same_day_away_high_attachment_types_desire_more_than_independent_types() -> None:
    high = {
        MbtiType.INFP: _after_day_away(MbtiType.INFP),
        MbtiType.ENFJ: _after_day_away(MbtiType.ENFJ),
        MbtiType.INFJ: _after_day_away(MbtiType.INFJ),
    }
    low = {
        MbtiType.INTP: _after_day_away(MbtiType.INTP),
        MbtiType.INTJ: _after_day_away(MbtiType.INTJ),
    }
    high_desire = min(item.closeness_desire for item in high.values())
    low_desire = max(item.closeness_desire for item in low.values())
    assert high_desire > low_desire
    # 高依恋不等于更高控制欲。
    assert all(item.exclusivity_need < 0.4 for item in high.values())


def test_same_rival_mention_differs_by_exclusivity_tendency() -> None:
    now = datetime(2026, 11, 7, 21, tzinfo=UTC)
    results: dict[MbtiType, tuple[float, float]] = {}
    for mbti in MbtiType:
        template = load_persona_templates()[mbti]
        progress = plan_attachment_progress(
            _relationship(attachment_strength=0.4, exclusivity_need=0.2),
            _emotion(),
            template.archive.relationship.attachment_disposition,
            collect_attachment_evidence(
                user_spoke=True,
                should_send=True,
                action=DialogueAction.REACT,
                self_motivation_kind=SelfMotivationKind.EXPRESS_EMOTION,
                relationship_motivation_kind=None,
                user_message="今天和女朋友约会，挺开心的",
                last_user_response_at=now - timedelta(minutes=10),
                now=now,
            ),
            fallback=False,
        )
        assert progress.relationship is not None
        assert progress.emotion is not None
        results[mbti] = (progress.relationship.exclusivity_need, progress.emotion.jealousy)

    enfj = results[MbtiType.ENFJ]
    intp = results[MbtiType.INTP]
    assert enfj[0] > intp[0]
    assert enfj[1] >= intp[1]
    # 所有人格都可以产生反应，但不因一次提及就锁死控制。
    assert all(need < 0.7 for need, _jealousy in results.values())


def test_same_affection_grows_faster_for_high_attachment_disposition() -> None:
    now = datetime(2026, 11, 7, 22, tzinfo=UTC)
    base = _relationship(attachment_strength=0.15, summary="初识阶段：有交流兴趣，依恋尚弱")
    grown: dict[MbtiType, float] = {}
    for mbti in MbtiType:
        template = load_persona_templates()[mbti]
        progress = plan_attachment_progress(
            base,
            _emotion(),
            template.archive.relationship.attachment_disposition,
            collect_attachment_evidence(
                user_spoke=True,
                should_send=True,
                action=DialogueAction.REACT,
                self_motivation_kind=SelfMotivationKind.EXPRESS_EMOTION,
                relationship_motivation_kind=SelfMotivationKind.SEEK_CONNECTION,
                user_message="我喜欢你，想你了",
                last_user_response_at=now - timedelta(minutes=2),
                now=now,
            ),
            fallback=False,
        )
        assert progress.relationship is not None
        grown[mbti] = progress.relationship.attachment_strength

    assert grown[MbtiType.INFP] > grown[MbtiType.INTP]
    assert grown[MbtiType.ENFP] > grown[MbtiType.INTJ]
    assert all(value < 0.55 for value in grown.values())


def test_space_request_is_respected_across_all_six_types() -> None:
    now = datetime(2026, 11, 7, 23, tzinfo=UTC)
    for mbti in MbtiType:
        template = load_persona_templates()[mbti]
        before = _relationship(closeness_desire=0.55, attachment_strength=0.4)
        progress = plan_attachment_progress(
            before,
            _emotion(),
            template.archive.relationship.attachment_disposition,
            collect_attachment_evidence(
                user_spoke=True,
                should_send=True,
                action=DialogueAction.RESPOND,
                self_motivation_kind=SelfMotivationKind.NONE,
                relationship_motivation_kind=None,
                user_message="我最近没时间陪伴，想独处一下",
                last_user_response_at=now - timedelta(minutes=5),
                now=now,
            ),
            fallback=False,
        )
        assert progress.relationship is not None
        assert progress.relationship.closeness_desire < before.closeness_desire
        assert progress.relationship.attachment_strength == before.attachment_strength


def test_all_six_self_models_allow_emotion_without_human_identity() -> None:
    templates = load_persona_templates()
    for template in templates.values():
        self_model = template.archive.self_model
        assert self_model.human_identity is False
        assert "情感" in self_model.emotional_capability or "依恋" in self_model.relationship_capability
        assert "询问" in self_model.disclosure_policy or "澄清" in self_model.disclosure_policy
        assert template.archive.relationship.relationship_preferences.emotional_boundaries


def test_proactive_silence_threshold_follows_attachment_readiness() -> None:
    early = required_user_silence(ProactiveAttachmentCue(closeness_desire=0.1, attachment_strength=0.05))
    medium = required_user_silence(ProactiveAttachmentCue(closeness_desire=0.35, attachment_strength=0.4))
    high = required_user_silence(
        ProactiveAttachmentCue(closeness_desire=0.7, attachment_strength=0.55, separation_sensitivity=0.6)
    )
    assert early == EARLY_STAGE_USER_SILENCE
    assert medium == MEDIUM_DESIRE_USER_SILENCE
    assert high == HIGH_DESIRE_USER_SILENCE
    assert high < medium < early

    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    messages = [ProactiveMessage("user", now - timedelta(hours=4))]
    assert (
        attachment_silence_block(
            messages,
            now,
            ProactiveAttachmentCue(closeness_desire=0.1, attachment_strength=0.05),
        )
        == "user_silence_too_short"
    )
    assert (
        attachment_silence_block(
            messages,
            now,
            ProactiveAttachmentCue(closeness_desire=0.7, attachment_strength=0.6),
        )
        is None
    )


def test_high_vs_low_separation_templates_match_expected_tendency() -> None:
    templates = load_persona_templates()
    assert templates[MbtiType.INFP].archive.relationship.attachment_disposition.separation_sensitivity == TendencyLevel.HIGH
    assert templates[MbtiType.ENFJ].archive.relationship.attachment_disposition.attachment_tendency == TendencyLevel.HIGH
    assert templates[MbtiType.INTP].archive.relationship.attachment_disposition.attachment_tendency == TendencyLevel.MEDIUM
    assert templates[MbtiType.INTP].archive.relationship.attachment_disposition.independence_need == TendencyLevel.HIGH
    assert templates[MbtiType.INTJ].archive.relationship.attachment_disposition.affection_expression == TendencyLevel.LOW
