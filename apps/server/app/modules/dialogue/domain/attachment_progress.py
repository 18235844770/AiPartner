"""根据可核对的交流证据渐进更新依恋状态。

不随聊天次数线性增长；旧的 closeness/trust/attachment/care 总分不在这里改动。
倾向只调节变化幅度与上限，不直接写成当前依恋。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.modules.dialogue.domain.enums import DialogueAction, SelfMotivationKind
from app.modules.persona.domain.archive import AttachmentDisposition, TendencyLevel
from app.modules.state.domain.snapshots import EmotionInput, EmotionState, RelationshipState

_THOUSANDTH = Decimal("0.001")
_INITIAL_SUMMARY = "状态初始化"
_GAP_NOTICE = timedelta(hours=18)
_LONG_GAP = timedelta(hours=36)

_MISS = ("想你", "想念你", "好想你", "想我了吗", "有想我", "我好想")
_AFFECTION = ("喜欢你", "爱你", "在乎你", "需要你", "离不开你", "只喜欢你")
_REASSURE = ("别难过", "我在", "陪着你", "没有不理你", "不是不理你", "哄哄你", "抱抱")
_SPACE = ("没时间", "先忙", "想独处", "别打扰", "以后再说", "今天先这样", "需要空间")
_RIVAL = ("约会", "女朋友", "男朋友", "对象", "表白", "谈恋爱", "出去玩了")

_CONNECTIVE = {DialogueAction.SHARE, DialogueAction.REACT, DialogueAction.CONTINUE}
_RELATION_MOTIVES = {
    SelfMotivationKind.SHOW_CARE,
    SelfMotivationKind.SEEK_CONNECTION,
    SelfMotivationKind.EXPRESS_EMOTION,
    SelfMotivationKind.SEEK_ATTENTION,
    SelfMotivationKind.RECALL_MEMORY,
}

_WEIGHT = {
    TendencyLevel.LOW: Decimal("0.55"),
    TendencyLevel.MEDIUM: Decimal("1.0"),
    TendencyLevel.HIGH: Decimal("1.45"),
}
_CAP = {
    TendencyLevel.LOW: Decimal("0.35"),
    TendencyLevel.MEDIUM: Decimal("0.65"),
    TendencyLevel.HIGH: Decimal("0.90"),
}


@dataclass(frozen=True)
class AttachmentEvidence:
    """本轮可核对的依恋相关证据。"""

    mutual_exchange: bool = False
    connective_action: bool = False
    relationship_motive: bool = False
    user_misses: bool = False
    user_affection: bool = False
    user_reassurance: bool = False
    user_needs_space: bool = False
    rival_mention: bool = False
    gap: timedelta | None = None


@dataclass(frozen=True)
class AttachmentProgress:
    relationship: RelationshipState | None
    emotion: EmotionInput | None
    reasons: tuple[str, ...]


def collect_attachment_evidence(
    *,
    user_spoke: bool,
    should_send: bool,
    action: DialogueAction,
    self_motivation_kind: SelfMotivationKind | None,
    relationship_motivation_kind: SelfMotivationKind | None,
    user_message: str | None,
    last_user_response_at: datetime | None,
    now: datetime,
) -> AttachmentEvidence:
    text = (user_message or "").strip()
    motive = relationship_motivation_kind or self_motivation_kind
    gap = None
    if user_spoke and last_user_response_at is not None:
        gap = _aware(now) - _aware(last_user_response_at)
        if gap < timedelta(0):
            gap = timedelta(0)
    return AttachmentEvidence(
        mutual_exchange=user_spoke and should_send,
        connective_action=action in _CONNECTIVE and should_send,
        relationship_motive=motive in _RELATION_MOTIVES if motive is not None else False,
        user_misses=_contains(text, _MISS),
        user_affection=_contains(text, _AFFECTION),
        user_reassurance=_contains(text, _REASSURE),
        user_needs_space=_contains(text, _SPACE),
        rival_mention=_contains(text, _RIVAL),
        gap=gap,
    )


def plan_attachment_progress(
    current: RelationshipState,
    emotion: EmotionState,
    disposition: AttachmentDisposition | None,
    evidence: AttachmentEvidence,
    *,
    fallback: bool,
) -> AttachmentProgress:
    """没有证据或降级回合时不改依恋；有证据时按倾向幅度更新。"""
    if fallback or not _has_progress_signal(evidence):
        if current.summary == _INITIAL_SUMMARY and (evidence.mutual_exchange or evidence.connective_action):
            updated = current.model_copy(update={"summary": _stage_summary(current.attachment_strength)})
            if updated != current:
                return AttachmentProgress(updated, None, ("交流已经开始",))
        return AttachmentProgress(None, None, ())

    disposition = disposition or _default_disposition()
    strength = Decimal(str(current.attachment_strength))
    reliance = Decimal(str(current.emotional_reliance))
    security = Decimal(str(current.relationship_security))
    specialness = Decimal(str(current.perceived_specialness))
    separation = Decimal(str(current.separation_sensitivity))
    reassurance = Decimal(str(current.reassurance_satisfaction))
    desire = Decimal(str(current.closeness_desire))
    exclusivity = Decimal(str(current.exclusivity_need))
    jealousy = Decimal(str(emotion.jealousy))
    possessiveness = Decimal(str(emotion.possessiveness))
    tension = Decimal(str(emotion.emotional_tension))
    triggers = list(emotion.triggers)
    reasons: list[str] = []

    att = _WEIGHT[disposition.attachment_tendency]
    dep = _WEIGHT[disposition.emotional_dependency_tendency]
    excl = _WEIGHT[disposition.exclusivity_tendency]
    sep = _WEIGHT[disposition.separation_sensitivity]
    reass = _WEIGHT[disposition.reassurance_need]
    indep = _WEIGHT[disposition.independence_need]
    cap = _CAP[disposition.attachment_tendency]
    reliance_cap = _CAP[disposition.emotional_dependency_tendency]

    if evidence.gap is not None and evidence.gap >= _GAP_NOTICE:
        desire = _clamp(desire + Decimal("0.04") * sep)
        reassurance = _clamp(reassurance - Decimal("0.03") * reass)
        separation = _clamp(separation + Decimal("0.02") * sep)
        tension = _clamp(tension + Decimal("0.03") * sep)
        _push_trigger(triggers, "久未联系")
        reasons.append("联系中断后提升靠近意愿")
        if evidence.gap >= _LONG_GAP:
            desire = _clamp(desire + Decimal("0.03") * sep)
            reasons.append("较长时间未联系")

    if evidence.user_needs_space:
        desire = _clamp(desire - Decimal("0.05"))
        exclusivity = _clamp(exclusivity - Decimal("0.02"))
        security = _clamp(security + Decimal("0.01"))
        reasons.append("用户需要空间，降低靠近压力")
    elif evidence.mutual_exchange:
        # 普通互回应增量很小，避免按次数线性堆高；用户要空间时不借互回抬升依恋。
        strength = _toward(strength, Decimal("0.006") * att, cap)
        security = _clamp(security + Decimal("0.008"))
        reasons.append("双方完成一次交流")

    if not evidence.user_needs_space and evidence.connective_action:
        strength = _toward(strength, Decimal("0.012") * att, cap)
        specialness = _clamp(specialness + Decimal("0.01") * att)
        reasons.append("本轮有连接性表达")

    if not evidence.user_needs_space and evidence.relationship_motive:
        desire = _clamp(desire + Decimal("0.015") * att)
        reasons.append("存在明确的关系动机")

    if evidence.user_misses or evidence.user_affection:
        bump = Decimal("0.035") if evidence.user_affection else Decimal("0.028")
        strength = _toward(strength, bump * att, cap)
        reliance = _toward(reliance, Decimal("0.02") * dep / indep, reliance_cap)
        specialness = _clamp(specialness + Decimal("0.04") * att)
        reassurance = _clamp(reassurance + Decimal("0.05"))
        desire = _clamp(desire + Decimal("0.02"))
        tension = _clamp(tension - Decimal("0.05"))
        reasons.append("用户表达了亲密或想念")

    if evidence.user_reassurance:
        reassurance = _clamp(reassurance + Decimal("0.07") * reass)
        security = _clamp(security + Decimal("0.03"))
        tension = _clamp(tension - Decimal("0.08"))
        jealousy = _clamp(jealousy - Decimal("0.05"))
        _discard_trigger(triggers, "久未联系")
        reasons.append("用户给予了安慰或确认")

    if evidence.rival_mention:
        exclusivity = _clamp(exclusivity + Decimal("0.04") * excl)
        specialness = _clamp(specialness - Decimal("0.02"))
        jealousy = _clamp(jealousy + Decimal("0.08") * _WEIGHT[disposition.jealousy_tendency])
        possessiveness = _clamp(
            possessiveness + Decimal("0.05") * _WEIGHT[disposition.possessiveness_tendency]
        )
        tension = _clamp(tension + Decimal("0.04"))
        _push_trigger(triggers, "提到其他亲密对象")
        reasons.append("提到其他亲密对象，独占相关需求上升")

    # 稳定互动会提高安全感，并缓和过度的确认焦虑。
    if (
        evidence.mutual_exchange
        and not evidence.rival_mention
        and not evidence.user_needs_space
        and strength >= Decimal("0.35")
    ):
        reassurance = _clamp(reassurance + Decimal("0.01"))
        if security >= Decimal("0.55"):
            desire = _clamp(desire - Decimal("0.01"))

    proposed = current.model_copy(
        update={
            "attachment_strength": float(strength),
            "emotional_reliance": float(reliance),
            "relationship_security": float(security),
            "perceived_specialness": float(specialness),
            "separation_sensitivity": float(separation),
            "reassurance_satisfaction": float(reassurance),
            "closeness_desire": float(desire),
            "exclusivity_need": float(exclusivity),
            "summary": _stage_summary(float(strength), current.summary),
        }
    )
    emotion_changed = (
        float(jealousy) != emotion.jealousy
        or float(possessiveness) != emotion.possessiveness
        or float(tension) != emotion.emotional_tension
        or triggers != list(emotion.triggers)
    )
    next_emotion = None
    if emotion_changed:
        next_emotion = EmotionInput(
            primary=emotion.primary,
            secondary=list(emotion.secondary),
            intensity=emotion.intensity,
            valence=emotion.valence,
            arousal=emotion.arousal,
            jealousy=float(jealousy),
            possessiveness=float(possessiveness),
            emotional_tension=float(tension),
            triggers=triggers,
            cause_summary=emotion.cause_summary if not reasons else "；".join(reasons[:2]),
        )
    if proposed == current and next_emotion is None:
        return AttachmentProgress(None, None, ())
    return AttachmentProgress(
        None if proposed == current else proposed,
        next_emotion,
        tuple(reasons),
    )


def _has_progress_signal(evidence: AttachmentEvidence) -> bool:
    return any(
        [
            evidence.mutual_exchange,
            evidence.connective_action,
            evidence.relationship_motive,
            evidence.user_misses,
            evidence.user_affection,
            evidence.user_reassurance,
            evidence.user_needs_space,
            evidence.rival_mention,
            evidence.gap is not None and evidence.gap >= _GAP_NOTICE,
        ]
    )


def _stage_summary(strength: float, current: str | None = None) -> str:
    if strength < 0.12:
        if current == _INITIAL_SUMMARY or current is None:
            return "初识阶段：有交流兴趣，依恋尚弱"
        return current if current.startswith("初识") else "初识阶段：有交流兴趣，依恋尚弱"
    if strength < 0.35:
        return "熟悉阶段：开始形成共同交流期待"
    if strength < 0.60:
        return "亲密阶段：情感连接正在加深"
    return "稳定依恋阶段：关系预期相对稳定"


def _default_disposition() -> AttachmentDisposition:
    return AttachmentDisposition(
        attachment_tendency=TendencyLevel.MEDIUM,
        emotional_dependency_tendency=TendencyLevel.MEDIUM,
        exclusivity_tendency=TendencyLevel.MEDIUM,
        separation_sensitivity=TendencyLevel.MEDIUM,
        reassurance_need=TendencyLevel.MEDIUM,
        affection_expression=TendencyLevel.MEDIUM,
        jealousy_tendency=TendencyLevel.MEDIUM,
        possessiveness_tendency=TendencyLevel.MEDIUM,
        independence_need=TendencyLevel.MEDIUM,
    )


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(phrase in text for phrase in phrases)


def _toward(value: Decimal, delta: Decimal, cap: Decimal) -> Decimal:
    if delta <= 0:
        return value
    room = cap - value
    if room <= 0:
        return _clamp(value)
    step = delta if delta < room else room
    return _clamp(value + step)


def _clamp(value: Decimal) -> Decimal:
    if value < 0:
        value = Decimal(0)
    if value > 1:
        value = Decimal(1)
    return value.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)


def _push_trigger(triggers: list[str], item: str) -> None:
    if item not in triggers:
        triggers.append(item)
    while len(triggers) > 4:
        triggers.pop(0)


def _discard_trigger(triggers: list[str], item: str) -> None:
    if item in triggers:
        triggers.remove(item)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
