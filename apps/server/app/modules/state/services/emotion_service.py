"""情绪公开服务：应用事件与衰减。最终写库仍走 StateService 同事务。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.modules.state.domain.emotion import (
    EmotionDeltaEvent,
    apply_events,
    decay_levels,
    levels_summary,
    normalize_levels,
    sync_legacy_from_levels,
)
from app.modules.state.domain.snapshots import EmotionInput, EmotionState


class EmotionService:
    """领域服务：计算下一情绪快照。不持有 Session，不自行提交。"""

    def apply_events(
        self,
        current: EmotionState,
        events: list[EmotionDeltaEvent],
        *,
        cause_summary: str | None = None,
        now: datetime | None = None,
    ) -> EmotionInput | None:
        del now
        if not events:
            return None
        after, deltas = apply_events(current.levels, events)
        if not deltas:
            return None
        return self._to_input(
            after,
            current,
            cause_summary=cause_summary or "；".join(event.reason for event in events[:3]),
        )

    def decay(
        self,
        current: EmotionState,
        *,
        elapsed: timedelta,
        cause_summary: str | None = None,
    ) -> EmotionInput | None:
        if elapsed.total_seconds() <= 0:
            return None
        after = decay_levels(current.levels, elapsed)
        if after == normalize_levels(current.levels):
            return None
        resting = all(value <= 0.01 for value in after.values())
        cause = cause_summary
        if cause is None:
            cause = "临时情绪已经过去" if resting else current.cause_summary
        return self._to_input(after, current, cause_summary=cause)

    def summarize(self, current: EmotionState) -> dict[str, object]:
        return levels_summary(current.levels)

    def _to_input(
        self,
        levels: dict[str, float],
        current: EmotionState,
        *,
        cause_summary: str,
    ) -> EmotionInput:
        legacy = sync_legacy_from_levels(levels)
        primary = str(legacy["primary"])
        secondary = [str(item) for item in legacy["secondary"]]  # type: ignore[index]
        return EmotionInput(
            primary=primary,
            secondary=secondary,
            intensity=float(legacy["intensity"]),
            valence=float(legacy["valence"]),
            arousal=float(legacy["arousal"]),
            jealousy=float(legacy["jealousy"]),
            possessiveness=current.possessiveness,
            emotional_tension=current.emotional_tension,
            triggers=list(current.triggers),
            cause_summary=cause_summary,
            levels=levels,
        )
