"""把已经执行的决策写成状态变化。关系数值不因一句话增减。"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.state.domain.enums import InteractionMode, MotivationKind
from app.modules.state.domain.snapshots import (
    EmotionInput,
    EmotionState,
    InteractionState,
    MotivationState,
    RelationshipState,
)

_INITIAL_RELATIONSHIP = "状态初始化"
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
    next_relationship = _relationship(relationship, user_spoke=user_spoke, should_send=should_send)
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
        pieces.append("关系里的初始化标记")
    if fallback:
        reason = "决策没有完成，只记录这次交流发生过"
    else:
        reason = "这一轮决策已经执行，更新" + "、".join(pieces)
        if next_relationship is not None:
            reason += "。关系数值保持原样"
    return TurnStateUpdate(
        reason=reason,
        emotion=next_emotion,
        relationship=next_relationship,
        interaction=next_interaction,
        motivation=next_motivation,
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
        cause_summary=cause,
    )
    current_input = EmotionInput(
        primary=current.primary,
        secondary=list(current.secondary),
        intensity=current.intensity,
        valence=current.valence,
        arousal=current.arousal,
        cause_summary=current.cause_summary,
    )
    if proposed == current_input:
        return None
    return proposed


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


def _relationship(
    current: RelationshipState,
    *,
    user_spoke: bool,
    should_send: bool,
) -> RelationshipState | None:
    if current.summary != _INITIAL_RELATIONSHIP or not (user_spoke or should_send):
        return None
    return current.model_copy(update={"summary": "已经开始交流，关系程度仍保持原来的判断"})
