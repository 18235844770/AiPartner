"""把已经执行的决策写成状态变化。

旧的 closeness/trust/attachment/care 总分不因普通一句话增减。
依恋状态字段只在有可核对证据时渐进更新。
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.dialogue.domain.attachment_progress import (
    AttachmentProgress,
    collect_attachment_evidence,
    plan_attachment_progress,
)
from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.dialogue.domain.relationship_assertion import (
    build_relationship_assertion,
    confrontation_persona_factor,
    resentment_persona_factor,
    user_message_has_friction,
)
from app.modules.persona.domain.archive import AttachmentDisposition, RelationshipSelfAssertion, default_self_assertion
from app.modules.state.domain.emotion import (
    ACTION_EMOTION_LABELS,
    EmotionDeltaEvent,
    EmotionEventKind,
    apply_events,
    emotion_display_name,
    normalize_levels,
    primary_from_levels,
    sync_legacy_from_levels,
)
from app.modules.state.domain.enums import InteractionEnergy, InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import (
    EmotionInput,
    EmotionState,
    InteractionState,
    MotivationState,
    RelationshipState,
)

_ASSERTION_MOTIVES = {
    SelfMotivationKind.ASSERT_STANCE,
    SelfMotivationKind.EXPRESS_GRIEVANCE,
    SelfMotivationKind.SEEK_ACKNOWLEDGMENT,
}
_NEGATIVE_PRESERVE = 20.0

_EMOTION = {
    DialogueAction.RESPOND: ("attentive", 0.25, 0.5, 0.25, "这一轮在听用户说话"),
    DialogueAction.SHARE: ("engaged", 0.5, 0.5, 0.5, "这一轮有自己想说的内容"),
    DialogueAction.ASK: ("curious", 0.5, 0.5, 0.25, "这一轮想把一件事弄清"),
    DialogueAction.REACT: ("moved", 0.5, 0.5, 0.5, "这一轮接住了对方的话"),
    DialogueAction.CONTINUE: ("engaged", 0.5, 0.5, 0.25, "这一轮还想把话题留住"),
    DialogueAction.CLOSE: ("calm", 0.0, 0.0, 0.0, "这一轮选择结束这次交流"),
    DialogueAction.QUIET: ("calm", 0.0, 0.0, 0.0, "这一轮选择不发消息"),
}
_EMOTION_EVENTS: dict[DialogueAction, EmotionEventKind] = {
    DialogueAction.RESPOND: EmotionEventKind.ATTENTIVE_LISTEN,
    DialogueAction.SHARE: EmotionEventKind.SHARED_INTEREST,
    DialogueAction.ASK: EmotionEventKind.CURIOSITY,
    DialogueAction.REACT: EmotionEventKind.POSITIVE_INTERACTION,
    DialogueAction.CONTINUE: EmotionEventKind.MEANINGFUL_CONVERSATION,
    DialogueAction.CLOSE: EmotionEventKind.QUIET_REST,
    DialogueAction.QUIET: EmotionEventKind.QUIET_REST,
}
_MOTIVATION = {
    DialogueAction.RESPOND: MotivationKind.LISTEN,
    DialogueAction.SHARE: MotivationKind.SHARE,
    DialogueAction.ASK: MotivationKind.UNDERSTAND,
    DialogueAction.REACT: MotivationKind.CONNECT,
    DialogueAction.CONTINUE: MotivationKind.CONNECT,
    DialogueAction.CLOSE: MotivationKind.REST,
    DialogueAction.QUIET: MotivationKind.REST,
}
_MOTIVATION_REASON = {
    DialogueAction.RESPOND: "这一轮主要在听",
    DialogueAction.SHARE: "这一轮主要想分享",
    DialogueAction.ASK: "这一轮主要想弄清一件事",
    DialogueAction.REACT: "这一轮主要在接住对方",
    DialogueAction.CONTINUE: "这一轮主要想把话题留住",
    DialogueAction.CLOSE: "这一轮主要想停下来",
    DialogueAction.QUIET: "这一轮主要选择不说",
}


@dataclass(frozen=True)
class TurnStateUpdate:
    reason: str
    emotion: EmotionInput | None = None
    relationship: RelationshipState | None = None
    interaction: InteractionState | None = None
    motivation: MotivationState | None = None


def plan_turn_state(
    *,
    action: DialogueAction,
    secondary_actions: list[DialogueAction],
    should_send: bool,
    fallback: bool,
    blocked: bool,
    confidence: float,
    emotion: EmotionState,
    relationship: RelationshipState,
    interaction: InteractionState,
    motivation: MotivationState,
    user_spoke: bool,
    now: datetime,
    disposition: AttachmentDisposition | None = None,
    self_assertion: RelationshipSelfAssertion | None = None,
    self_motivation_kind: SelfMotivationKind | None = None,
    relationship_motivation_kind: SelfMotivationKind | None = None,
    user_message: str | None = None,
) -> TurnStateUpdate | None:
    """被拦住，或模型失败且这一轮没有发生交流时，不写状态。"""
    if blocked or (fallback and not user_spoke and not should_send):
        return None
    assertion = self_assertion or default_self_assertion()
    next_interaction = _interaction(
        interaction,
        should_send=should_send,
        user_spoke=user_spoke,
        now=now,
    )
    next_emotion = None if fallback else _emotion(
        action,
        emotion,
        self_motivation_kind=self_motivation_kind,
        relationship_motivation_kind=relationship_motivation_kind,
        user_message=user_message,
        self_assertion=assertion,
    )
    next_motivation = None if fallback else _motivation(action, secondary_actions, confidence, motivation)
    intimacy_dampen = _intimacy_dampen(emotion.levels, assertion)
    attachment = _attachment(
        relationship,
        emotion if next_emotion is None else _emotion_state_from_input(next_emotion, emotion),
        disposition,
        user_spoke=user_spoke,
        should_send=should_send,
        action=action,
        self_motivation_kind=self_motivation_kind,
        relationship_motivation_kind=relationship_motivation_kind,
        user_message=user_message,
        last_user_response_at=interaction.last_user_response_at,
        now=now,
        fallback=fallback,
        intimacy_dampen=intimacy_dampen,
    )
    next_relationship = attachment.relationship
    if attachment.emotion is not None:
        next_emotion = _merge_emotion(next_emotion, attachment.emotion, emotion)
    if (
        next_emotion is None
        and next_relationship is None
        and next_interaction is None
        and next_motivation is None
    ):
        return None
    pieces: list[str] = []
    if next_emotion is not None:
        pieces.append("情绪")
    if next_interaction is not None:
        pieces.append("交流")
    if next_motivation is not None:
        pieces.append("动机")
    if next_relationship is not None:
        pieces.append("依恋状态" if attachment.reasons else "关系摘要")
    if fallback:
        reason = "决策没有完成，只记录这次交流发生过"
    else:
        reason = "这一轮决策已经执行，更新" + "、".join(pieces)
        if attachment.reasons:
            reason += "。依据：" + "；".join(attachment.reasons)
        elif next_relationship is not None:
            reason += "。关系总分保持原样，仅更新依恋相关状态"
    return TurnStateUpdate(
        reason=reason,
        emotion=next_emotion,
        relationship=next_relationship,
        interaction=next_interaction,
        motivation=next_motivation,
    )


def _attachment(
    current: RelationshipState,
    emotion: EmotionState,
    disposition: AttachmentDisposition | None,
    *,
    user_spoke: bool,
    should_send: bool,
    action: DialogueAction,
    self_motivation_kind: SelfMotivationKind | None,
    relationship_motivation_kind: SelfMotivationKind | None,
    user_message: str | None,
    last_user_response_at: datetime | None,
    now: datetime,
    fallback: bool,
    intimacy_dampen: float = 0.0,
) -> AttachmentProgress:
    evidence = collect_attachment_evidence(
        user_spoke=user_spoke,
        should_send=should_send,
        action=action,
        self_motivation_kind=self_motivation_kind,
        relationship_motivation_kind=relationship_motivation_kind,
        user_message=user_message,
        last_user_response_at=last_user_response_at,
        now=now,
    )
    return plan_attachment_progress(
        current,
        emotion,
        disposition,
        evidence,
        fallback=fallback,
        intimacy_dampen=intimacy_dampen,
    )


def _interaction(
    current: InteractionState,
    *,
    should_send: bool,
    user_spoke: bool,
    now: datetime,
) -> InteractionState | None:
    if not user_spoke and not should_send:
        return None
    updated = current.model_copy(deep=True)
    if user_spoke:
        updated.last_user_response_at = now
        updated.consecutive_unanswered_messages = 1 if should_send else 0
        updated.waiting_for_user = should_send
        if should_send:
            updated.consecutive_quiet_turns = 0
        else:
            updated.consecutive_quiet_turns = current.consecutive_quiet_turns + 1
        if current.mode == InteractionMode.QUIET:
            updated.mode = InteractionMode.AVAILABLE
            updated.quiet_until = None
        if current.energy == InteractionEnergy.QUIET:
            updated.energy = InteractionEnergy.NORMAL
    if should_send:
        updated.last_companion_message_at = now
        updated.consecutive_quiet_turns = 0
        if not user_spoke:
            updated.consecutive_unanswered_messages = current.consecutive_unanswered_messages + 1
            updated.waiting_for_user = True
    if updated == current:
        return None
    return updated


def _emotion(
    action: DialogueAction,
    current: EmotionState,
    *,
    self_motivation_kind: SelfMotivationKind | None,
    relationship_motivation_kind: SelfMotivationKind | None,
    user_message: str | None,
    self_assertion: RelationshipSelfAssertion,
) -> EmotionInput | None:
    primary_key, intensity, valence, arousal, cause = _EMOTION[action]
    action_label = ACTION_EMOTION_LABELS.get(primary_key, emotion_display_name(primary_key))
    levels_now = normalize_levels(current.levels)
    preserve = max(levels_now["anger"], levels_now["hurt"]) >= _NEGATIVE_PRESERVE
    mild_intensity = 0.18 if preserve else 0.45
    events = [
        EmotionDeltaEvent(
            kind=_EMOTION_EVENTS[action],
            intensity=mild_intensity,
            confidence=1.0,
            reason=cause,
        )
    ]
    events.extend(
        _conflict_events(
            self_motivation_kind=self_motivation_kind,
            relationship_motivation_kind=relationship_motivation_kind,
            user_message=user_message,
            self_assertion=self_assertion,
        )
    )
    after_levels, deltas = apply_events(current.levels, events)
    if preserve:
        after_levels = _preserve_negative(levels_now, after_levels)
    causes = [cause]
    for item in events[1:]:
        causes.append(item.reason)
    cause_summary = "；".join(causes)
    legacy = sync_legacy_from_levels(after_levels) if deltas else None
    if legacy is None:
        levels = normalize_levels(after_levels)
        proposed = EmotionInput(
            primary=primary_from_levels(levels, fallback=action_label),
            secondary=[],
            intensity=intensity,
            valence=valence,
            arousal=arousal,
            jealousy=current.jealousy,
            possessiveness=current.possessiveness,
            emotional_tension=current.emotional_tension,
            triggers=list(current.triggers),
            cause_summary=cause_summary,
            levels=levels,
        )
    else:
        derived_intensity = float(legacy["intensity"])
        proposed = EmotionInput(
            primary=primary_from_levels(after_levels, fallback=action_label),
            secondary=[str(item) for item in legacy["secondary"]],  # type: ignore[index]
            intensity=max(intensity, derived_intensity),
            valence=float(legacy["valence"]),
            arousal=float(legacy["arousal"]),
            jealousy=float(legacy["jealousy"]),
            possessiveness=current.possessiveness,
            emotional_tension=current.emotional_tension,
            triggers=list(current.triggers),
            cause_summary=cause_summary,
            levels=after_levels,
        )
    current_input = EmotionInput(
        primary=current.primary,
        secondary=list(current.secondary),
        intensity=current.intensity,
        valence=current.valence,
        arousal=current.arousal,
        jealousy=current.jealousy,
        possessiveness=current.possessiveness,
        emotional_tension=current.emotional_tension,
        triggers=list(current.triggers),
        cause_summary=current.cause_summary,
        levels=normalize_levels(current.levels),
    )
    if proposed == current_input:
        return None
    return proposed


def _conflict_events(
    *,
    self_motivation_kind: SelfMotivationKind | None,
    relationship_motivation_kind: SelfMotivationKind | None,
    user_message: str | None,
    self_assertion: RelationshipSelfAssertion,
) -> list[EmotionDeltaEvent]:
    motive = relationship_motivation_kind or self_motivation_kind
    friction = user_message_has_friction(user_message)
    events: list[EmotionDeltaEvent] = []
    resent = resentment_persona_factor(self_assertion.resentment_tendency)
    confront = confrontation_persona_factor(self_assertion.confrontation_tendency)
    if motive == SelfMotivationKind.EXPRESS_GRIEVANCE or (friction and motive in _ASSERTION_MOTIVES):
        events.append(
            EmotionDeltaEvent(
                kind=EmotionEventKind.CONFLICT,
                intensity=0.55,
                confidence=1.0,
                persona_factor=max(resent, confront),
                reason="关系摩擦被明确表达或触达",
            )
        )
    elif motive == SelfMotivationKind.ASSERT_STANCE and friction:
        events.append(
            EmotionDeltaEvent(
                kind=EmotionEventKind.DISAPPOINTMENT,
                intensity=0.5,
                confidence=1.0,
                persona_factor=resent,
                reason="感受被否定后坚持立场",
            )
        )
    elif motive == SelfMotivationKind.SEEK_ACKNOWLEDGMENT:
        events.append(
            EmotionDeltaEvent(
                kind=EmotionEventKind.DISAPPOINTMENT,
                intensity=0.4,
                confidence=1.0,
                persona_factor=resent,
                reason="希望对方理解未满足的关系需求",
            )
        )
    elif friction:
        events.append(
            EmotionDeltaEvent(
                kind=EmotionEventKind.REJECTION,
                intensity=0.4,
                confidence=0.9,
                persona_factor=resent,
                reason="用户话语含有否定或轻视感受的痕迹",
            )
        )
    return events


def _preserve_negative(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """冲突未解时，mild 正向事件不得把愤怒/委屈冲掉。"""
    merged = dict(after)
    for key in ("anger", "hurt", "sadness"):
        if before.get(key, 0.0) >= _NEGATIVE_PRESERVE:
            merged[key] = max(float(after.get(key, 0.0)), float(before[key]) * 0.92)
    return merged


def _intimacy_dampen(levels: dict[str, float] | None, assertion: RelationshipSelfAssertion) -> float:
    return build_relationship_assertion(assertion, levels).intimacy_dampen


def _merge_emotion(
    base: EmotionInput | None,
    attachment_emotion: EmotionInput,
    current: EmotionState,
) -> EmotionInput:
    """保留回合主情绪，合并依恋证据带来的关系情绪分量。"""
    if base is None:
        return attachment_emotion
    cause = base.cause_summary
    if attachment_emotion.cause_summary and attachment_emotion.cause_summary not in cause:
        cause = f"{base.cause_summary}；{attachment_emotion.cause_summary}"
    levels = normalize_levels(base.levels)
    levels["jealousy"] = round(attachment_emotion.jealousy * 100.0, 2)
    return base.model_copy(
        update={
            "jealousy": attachment_emotion.jealousy,
            "possessiveness": attachment_emotion.possessiveness,
            "emotional_tension": attachment_emotion.emotional_tension,
            "triggers": list(attachment_emotion.triggers),
            "cause_summary": cause,
            "levels": levels,
        }
    )


def _emotion_state_from_input(value: EmotionInput, current: EmotionState) -> EmotionState:
    return EmotionState(
        primary=value.primary,
        secondary=list(value.secondary),
        intensity=value.intensity,
        valence=value.valence,
        arousal=value.arousal,
        jealousy=value.jealousy,
        possessiveness=value.possessiveness,
        emotional_tension=value.emotional_tension,
        triggers=list(value.triggers),
        cause_summary=value.cause_summary,
        levels=normalize_levels(value.levels),
        updated_at=current.updated_at,
    )


def _motivation(
    action: DialogueAction,
    secondary_actions: list[DialogueAction],
    confidence: float,
    current: MotivationState,
) -> MotivationState | None:
    primary = _MOTIVATION[action]
    secondary: list[MotivationKind] = []
    for item in secondary_actions:
        kind = _MOTIVATION[item]
        if kind != primary and kind not in secondary:
            secondary.append(kind)
    intensity = confidence
    if intensity < 0:
        intensity = 0
    if intensity > 1:
        intensity = 1
    proposed = MotivationState(
        primary=primary,
        secondary=secondary,
        intensity=intensity,
        target=None if primary == MotivationKind.REST else "user",
        reason=_MOTIVATION_REASON[action],
    )
    if proposed == current:
        return None
    return proposed
