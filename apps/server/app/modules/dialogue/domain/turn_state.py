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
from app.modules.persona.domain.archive import AttachmentDisposition
from app.modules.state.domain.enums import InteractionEnergy, InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import (
    EmotionInput,
    EmotionState,
    InteractionState,
    MotivationState,
    RelationshipState,
)

_EMOTION = {
    DialogueAction.RESPOND: ("attentive", 0.25, 0.5, 0.25, "这一轮在听用户说话"),
    DialogueAction.SHARE: ("engaged", 0.5, 0.5, 0.5, "这一轮有自己想说的内容"),
    DialogueAction.ASK: ("curious", 0.5, 0.5, 0.25, "这一轮想把一件事弄清"),
    DialogueAction.REACT: ("moved", 0.5, 0.5, 0.5, "这一轮接住了对方的话"),
    DialogueAction.CONTINUE: ("engaged", 0.5, 0.5, 0.25, "这一轮还想把话题留住"),
    DialogueAction.CLOSE: ("calm", 0.0, 0.0, 0.0, "这一轮选择结束这次交流"),
    DialogueAction.QUIET: ("calm", 0.0, 0.0, 0.0, "这一轮选择不发消息"),
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
    self_motivation_kind: SelfMotivationKind | None = None,
    relationship_motivation_kind: SelfMotivationKind | None = None,
    user_message: str | None = None,
) -> TurnStateUpdate | None:
    """被拦住，或模型失败且这一轮没有发生交流时，不写状态。"""
    if blocked or (fallback and not user_spoke and not should_send):
        return None
    next_interaction = _interaction(
        interaction,
        should_send=should_send,
        user_spoke=user_spoke,
        now=now,
    )
    next_emotion = None if fallback else _emotion(action, emotion)
    next_motivation = None if fallback else _motivation(action, secondary_actions, confidence, motivation)
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
        if current.mode == InteractionMode.QUIET:
            updated.mode = InteractionMode.AVAILABLE
            updated.quiet_until = None
        if current.energy == InteractionEnergy.QUIET:
            updated.energy = InteractionEnergy.NORMAL
    if should_send:
        updated.last_companion_message_at = now
        if not user_spoke:
            updated.consecutive_unanswered_messages = current.consecutive_unanswered_messages + 1
            updated.waiting_for_user = True
    if updated == current:
        return None
    return updated


def _emotion(action: DialogueAction, current: EmotionState) -> EmotionInput | None:
    primary, intensity, valence, arousal, cause = _EMOTION[action]
    proposed = EmotionInput(
        primary=primary,
        secondary=[],
        intensity=intensity,
        valence=valence,
        arousal=arousal,
        jealousy=current.jealousy,
        possessiveness=current.possessiveness,
        emotional_tension=current.emotional_tension,
        triggers=list(current.triggers),
        cause_summary=cause,
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
    )
    if proposed == current_input:
        return None
    return proposed


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
    return base.model_copy(
        update={
            "jealousy": attachment_emotion.jealousy,
            "possessiveness": attachment_emotion.possessiveness,
            "emotional_tension": attachment_emotion.emotional_tension,
            "triggers": list(attachment_emotion.triggers),
            "cause_summary": cause,
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
