from datetime import UTC, datetime, timedelta

from app.modules.state.domain.emotion import (
    EmotionDeltaEvent,
    EmotionEventKind,
    apply_events,
    clamp_level,
    decay_levels,
    default_levels,
    dominant_emotion,
    levels_summary,
    normalize_levels,
)
from app.modules.state.domain.snapshots import EmotionState, initial_snapshots
from app.modules.state.services.emotion_service import EmotionService


def test_default_levels_cover_ten_emotions() -> None:
    levels = default_levels()
    assert set(levels) == {
        "joy",
        "affection",
        "longing",
        "comfort",
        "excitement",
        "sadness",
        "anxiety",
        "jealousy",
        "anger",
        "hurt",
    }
    assert all(value == 0 for value in levels.values())


def test_apply_events_clamps_and_deduplicates() -> None:
    before = default_levels()
    events = [
        EmotionDeltaEvent(
            kind=EmotionEventKind.POSITIVE_INTERACTION,
            intensity=1,
            confidence=1,
            reason="开心交流",
            source_message_id="m1",
        ),
        EmotionDeltaEvent(
            kind=EmotionEventKind.POSITIVE_INTERACTION,
            intensity=1,
            confidence=1,
            reason="重复同一条",
            source_message_id="m1",
        ),
        EmotionDeltaEvent(
            kind=EmotionEventKind.CONFLICT,
            intensity=1,
            confidence=1,
            reason="冲突",
            source_message_id="m2",
        ),
    ]
    after, deltas = apply_events(before, events)
    assert deltas["joy"] == clamp_level(8)
    assert "anger" in deltas
    assert after["joy"] == clamp_level(8)
    assert after["anger"] > 0
    # 同一 message+kind 不叠加
    again, _ = apply_events(before, events[:2])
    assert again["joy"] == after["joy"]


def test_decay_is_monotonic_toward_baseline() -> None:
    levels = default_levels()
    levels["joy"] = 80
    levels["affection"] = 60
    mid = decay_levels(levels, timedelta(hours=6))
    later = decay_levels(levels, timedelta(hours=24))
    assert mid["joy"] < levels["joy"]
    assert later["joy"] < mid["joy"]
    assert mid["affection"] < levels["affection"]
    assert later["affection"] <= mid["affection"]
    assert all(value >= 0 for value in later.values())


def test_emotion_service_apply_and_summarize() -> None:
    now = datetime(2026, 11, 7, tzinfo=UTC)
    current = EmotionState(
        primary="calm",
        intensity=0,
        valence=0,
        arousal=0,
        cause_summary="状态初始化",
        levels=default_levels(),
        updated_at=now,
    )
    service = EmotionService()
    updated = service.apply_events(
        current,
        [
            EmotionDeltaEvent(
                kind=EmotionEventKind.AFFECTION_EXPRESSION,
                intensity=1.0,
                confidence=1.0,
                reason="用户表达亲密",
            )
        ],
    )
    assert updated is not None
    assert updated.levels["affection"] >= 10
    assert updated.levels["joy"] > 0
    # 单次事件可能仍低于 active 阈值，主导仍可为 calm；摘要结构要可用。
    summary = levels_summary(updated.levels)
    assert "dominant" in summary
    assert isinstance(summary["active"], list)
    assert dominant_emotion({"affection": 80, **{k: 0 for k in default_levels() if k != "affection"}}) == "affection"


def test_initial_snapshots_include_levels_and_quiet_counter() -> None:
    snaps = initial_snapshots(datetime(2026, 11, 7, tzinfo=UTC))
    emotion = snaps["emotion"]
    interaction = snaps["interaction"]
    assert isinstance(emotion, EmotionState)
    assert normalize_levels(emotion.levels) == default_levels()
    assert interaction.consecutive_quiet_turns == 0
