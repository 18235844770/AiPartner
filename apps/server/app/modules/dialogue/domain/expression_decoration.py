"""正文定稿后补表情。模型不自己挑，语音侧仍会去掉这些符号。"""

from __future__ import annotations

import hashlib
import random

from app.modules.dialogue.domain.speech_turn import asks_for_guidance
from app.modules.persona.domain.expression_marks import ExpressionCatalog, ExpressionItem, load_expression_catalog

_INTENSITY = {"低": 1, "中": 2, "中高": 3, "高": 4, "极高": 5}
_EMOTION_ALIAS = {"longing": "affection", "calm": "comfort"}
_STRONG_EMOTIONS = {"anger", "excitement", "hurt", "sadness", "jealousy"}


def decorate_reply(
    text: str,
    *,
    mbti_type: str,
    emotion: str,
    action: str,
    user_text: str,
    recent_messages: list[dict[str, str]] | None = None,
    fact_correct: bool = False,
    strong: bool = False,
    catalog: ExpressionCatalog | None = None,
    rng: random.Random | None = None,
) -> str:
    """去掉模型自带的表情，再按情绪、人格和上一句决定要不要补。"""
    book = catalog or load_expression_catalog()
    plain = _plain_text(text, book)
    if not plain or action == "quiet" or fact_correct or asks_for_guidance(user_text):
        return plain
    style = book.persona_styles.get(mbti_type) or book.persona_styles.get("INFJ")
    if style is None:
        return plain
    used = _recent_marks(recent_messages or [], book)
    emotion_key = _EMOTION_ALIAS.get(emotion, emotion)
    rule = next((item for item in book.emotion_mapping if item.emotion == emotion_key), None)
    discouraged = set(rule.discouraged) if rule is not None else set()
    cap = _INTENSITY.get(style.max_intensity, 2)
    if action == "close":
        cap = min(cap, _INTENSITY["中"])
    recommended = rule.recommended if rule is not None else []
    emoji_rate = style.emoji_rate
    kaomoji_rate = style.kaomoji_rate
    if emotion in {"", "calm"} or action == "ask":
        emoji_rate *= 0.5
        kaomoji_rate *= 0.5
    if strong or emotion in _STRONG_EMOTIONS:
        emoji_rate = max(emoji_rate, book.frequency.strong_emotion_probability["min"])
        emoji_rate = min(emoji_rate, book.frequency.strong_emotion_probability["max"])
    chosen: list[str] = []
    if _roll(rng, f"{plain}|{mbti_type}|{emotion}|emoji") < emoji_rate:
        mark = _pick(book, recommended, discouraged, used, cap, "emoji", style.preferred_groups, plain, rng)
        if mark is not None:
            chosen.append(mark)
            used.add(mark)
    if action != "ask" and _roll(rng, f"{plain}|{mbti_type}|{emotion}|kaomoji") < kaomoji_rate:
        mark = _pick(book, recommended, discouraged, used, cap, "kaomoji", style.preferred_groups, plain, rng)
        if mark is not None:
            chosen.append(mark)
    if not chosen:
        return plain
    return f"{plain} {' '.join(chosen[: book.frequency.max_emoji_per_message + book.frequency.max_kaomoji_per_message])}"


def _plain_text(text: str, catalog: ExpressionCatalog) -> str:
    del catalog
    from app.shared.speech_marks import strip_non_speech_marks

    return strip_non_speech_marks(text)


def _recent_marks(recent_messages: list[dict[str, str]], catalog: ExpressionCatalog) -> set[str]:
    for item in reversed(recent_messages):
        sender = item.get("sender_type") or item.get("role")
        if sender not in {"companion", "assistant"}:
            continue
        content = item.get("content") or ""
        found = {mark for mark in catalog.by_mark if mark and mark in content}
        return found
    return set()


def _roll(rng: random.Random | None, key: str) -> float:
    if rng is not None:
        return rng.random()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _pick(
    catalog: ExpressionCatalog,
    recommended: list[str],
    discouraged: set[str],
    used: set[str],
    cap: int,
    kind: str,
    preferred_groups: list[str],
    plain: str,
    rng: random.Random | None,
) -> str | None:
    pool: list[ExpressionItem] = []
    for mark in recommended:
        item = catalog.by_mark.get(mark)
        if item is None or item.kind != kind:
            continue
        if mark in discouraged or mark in used:
            continue
        if _INTENSITY.get(item.intensity, 2) > cap:
            continue
        pool.append(item)
    if not pool:
        groups = catalog.emoji if kind == "emoji" else catalog.kaomoji_groups
        for group in groups:
            if preferred_groups and group.id not in preferred_groups:
                continue
            for item in group.items:
                if item.mark in discouraged or item.mark in used:
                    continue
                if _INTENSITY.get(item.intensity, 2) > cap:
                    continue
                pool.append(item)
    if not pool:
        return None
    preferred = [item for item in pool if item.group_id in preferred_groups]
    pool = preferred or pool
    ordered = sorted(pool, key=lambda item: item.mark)
    if rng is None:
        index = int(_roll(None, f"{plain}|{kind}|choice") * len(ordered))
        return ordered[min(index, len(ordered) - 1)].mark
    return rng.choice(ordered).mark
