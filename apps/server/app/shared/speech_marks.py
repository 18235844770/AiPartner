"""从朗读文本里去掉颜文字和 emoji。界面保留原文，语音不读这些符号。"""

from __future__ import annotations

import re

# 表情符号、变体选择符、零宽连接符、肤色修饰。
_EMOJI = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002300-\U000023FF"
    "\U00002B00-\U00002BFF"
    "\U0001F3FB-\U0001F3FF"
    "\u200D"
    "\uFE0F"
    "\u20E3"
    "]+"
)

# 括号里没有汉字，视为颜文字。含汉字的括号保留，例如（明天再说）。
_KAOMOJI_PAREN = re.compile(r"[\(（][^()\n（）\u4e00-\u9fff]{1,32}[\)）]")
_FACE_CLUSTER = re.compile(r"ಠ[_\s]*益[_\s]*ಠ")
_EMPTY_PAREN = re.compile(r"[\(（]\s*[\)）]")

_BARE_FACE = re.compile(
    r"(?<![\w\u4e00-\u9fff])"
    r"(?:QAQ|QwQ|TAT|T\^T|T_T|orz|Orz|ORZ|OwO|owo|UwU|uwu|>_<|\^_\^|\^-\^|;_;|:\)|:\(|:D|;\)|XD|xD)"
    r"(?![\w\u4e00-\u9fff])"
)

# 颜文字里常见、正常中文句子不会单独使用的符号。
_DECOR = re.compile(
    r"[╮╭ﾉノヽつДдεзω・･｡´`≧≦▽◕◔ಠ✿ﾟ๑ㅂو✧♡♥❤☆★∀σ□△ゝゞ￣＾ᴗ˘˶ᵕ◡ᴥᗜʕʔᵔᴖʃƪ•́̀︿]+"
)


def strip_non_speech_marks(text: str) -> str:
    """去掉颜文字和 emoji，留下可以朗读的正文。"""
    cleaned = _EMOJI.sub("", text)
    cleaned = _FACE_CLUSTER.sub("", cleaned)
    cleaned = _KAOMOJI_PAREN.sub("", cleaned)
    cleaned = _BARE_FACE.sub("", cleaned)
    cleaned = _DECOR.sub("", cleaned)
    cleaned = _EMPTY_PAREN.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([，。！？、；：,.!?])", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]+|[ \t]+$", "", cleaned)
    return cleaned.strip()
