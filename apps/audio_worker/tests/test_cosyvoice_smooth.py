"""CosyVoice 分段与平滑拼接（不加载真实模型）。"""

from __future__ import annotations

import torch

from audio_worker.backends.cosyvoice import (
    _concat_tensors_smooth,
    _split_speak_segments,
    normalize_cosyvoice_instruct,
)


def test_normalize_instruct_appends_endofprompt() -> None:
    out = normalize_cosyvoice_instruct("Speak naturally and calmly.")
    assert out.endswith("<|endofprompt|>")
    assert "You are a helpful assistant." in out
    assert out.count("<|endofprompt|>") == 1


def test_normalize_instruct_rejects_cjk() -> None:
    out = normalize_cosyvoice_instruct("用开心的语气说")
    assert "用开心" not in out
    assert out.endswith("<|endofprompt|>")



def test_split_keeps_short_text_intact() -> None:
    text = "你好，今天过得怎么样？"
    assert _split_speak_segments(text, max_chars=72) == [text]


def test_split_breaks_on_sentence_boundaries() -> None:
    text = "第一句。第二句很长很长很长很长很长。第三句！"
    segs = _split_speak_segments(text, max_chars=18)
    assert all(len(s) <= 18 or "。" in s or "！" in s for s in segs)
    assert "".join(segs) == text.replace(" ", "")
    assert len(segs) >= 2


def test_crossfade_shortens_joint() -> None:
    a = torch.ones(1, 2400)
    b = torch.ones(1, 2400) * 0.5
    hard = a.shape[-1] + b.shape[-1]
    out = _concat_tensors_smooth([a, b], 24000, fade_ms=28.0)
    assert out.shape[-1] < hard
    assert out.shape[-1] > 2400
