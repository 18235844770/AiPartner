"""把定稿拆成连续几条消息。决策不变，只改变发送形态。"""

from __future__ import annotations

import re

from app.shared.speech_marks import strip_non_speech_marks

_SENTENCE_BREAK = re.compile(r"[。！？!?]")
_STREAM_SENTENCE_END = re.compile(r"""[。！？!?]+[”’」』）"']*""")
_CLAUSE_BREAK = re.compile(r"[，,]")
_END_PUNCT = re.compile(r"[。．.，,、]+$")
_MIN_SPOKEN = 18
_LONG_CLAUSE = 36
_MIN_CLAUSE = 8
MAX_MESSAGES = 3


def take_completed_sentence(text: str) -> tuple[str, str] | None:
    """从模型流中取出已结束、能独立发送的句子。"""
    for match in _STREAM_SENTENCE_END.finditer(text):
        start, end = match.span()
        if _spoken_len(text[:start]) >= _MIN_CLAUSE:
            return text[:end], text[end:]
    return None


def split_companion_messages(text: str) -> list[str]:
    """短句保持一条。稍长的正文按句子拆开，最多三条。

    每条末尾不留句号或逗号。问号和感叹号保留。
    """
    raw = text.strip()
    if not raw:
        return []
    if _spoken_len(raw) < _MIN_SPOKEN:
        presented = present_companion_message(raw)
        return [presented] if presented else []
    units = _sentence_units(raw)
    expanded: list[str] = []
    for unit in units:
        expanded.extend(_clause_units(unit))
    pieces = [item.strip() for item in _merge_short(expanded) if item.strip()]
    if len(pieces) <= 1:
        presented = present_companion_message(raw)
        return [presented] if presented else []
    if len(pieces) > MAX_MESSAGES:
        tail_count = MAX_MESSAGES - 1
        pieces = ["".join(pieces[:-tail_count]).strip(), *pieces[-tail_count:]]
    presented = [item for item in (present_companion_message(part) for part in pieces) if item]
    return presented or [present_companion_message(raw)]


def _sentence_units(text: str) -> list[str]:
    return _merge_unspoken(_slices(text, _SENTENCE_BREAK), text)


def _clause_units(sentence: str) -> list[str]:
    if _spoken_len(sentence) <= _LONG_CLAUSE or _CLAUSE_BREAK.search(sentence) is None:
        return [sentence]
    return _merge_unspoken(_slices(sentence, _CLAUSE_BREAK), sentence)


def _slices(text: str, pattern: re.Pattern[str]) -> list[str]:
    pieces: list[str] = []
    start = 0
    for match in pattern.finditer(text):
        pieces.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    return [piece for piece in pieces if piece.strip()]


def _merge_unspoken(pieces: list[str], source: str) -> list[str]:
    del source
    merged: list[str] = []
    for piece in pieces:
        if merged and _spoken_len(piece) == 0:
            merged[-1] = f"{merged[-1]}{piece}"
        else:
            merged.append(piece)
    return merged or pieces


def _merge_short(pieces: list[str]) -> list[str]:
    merged: list[str] = []
    for piece in pieces:
        if merged and _spoken_len(piece) < _MIN_CLAUSE:
            merged[-1] = f"{merged[-1]}{piece}"
        else:
            merged.append(piece)
    return merged


def present_companion_message(piece: str) -> str:
    """去掉消息末尾的句号和逗号，问号和感叹号留在原文里。"""
    text = piece.strip()
    if not text:
        return ""
    spoken = strip_non_speech_marks(text).rstrip()
    if not spoken:
        return text
    index = text.rfind(spoken)
    if index < 0:
        return _END_PUNCT.sub("", text).strip()
    body = _END_PUNCT.sub("", text[index : index + len(spoken)].rstrip()).rstrip()
    tail = text[index + len(spoken) :].strip()
    core = f"{text[:index].rstrip()}{body}".strip()
    if tail:
        return f"{core} {tail}".strip()
    return core


def _spoken_len(text: str) -> int:
    return len(strip_non_speech_marks(text).strip())
