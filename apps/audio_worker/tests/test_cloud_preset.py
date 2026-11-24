import struct

from audio_worker.backends.cloud_preset import fish_text, repair_wav, wav_duration_ms


def test_fish_text_puts_instruction_in_brackets() -> None:
    assert fish_text("你好。", "语气自然") == "[语气自然]\n你好。"
    assert fish_text("你好。", "  ") == "你好。"


def test_repair_wav_rewrites_streaming_sizes() -> None:
    pcm = b"\x01\x00" * 240
    broken = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        0xFFFFFFFF,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        24000,
        48000,
        2,
        16,
        b"data",
        0xFFFFFFFF,
    ) + pcm
    repaired = repair_wav(broken, 24000)
    assert repaired[4:8] != b"\xff\xff\xff\xff"
    assert wav_duration_ms(repaired) == 10
