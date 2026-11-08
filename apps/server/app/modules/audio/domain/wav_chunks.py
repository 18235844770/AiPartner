"""把完整 WAV 切成可独立播放的小 WAV，用于 SSE 分块下发。"""

from __future__ import annotations

import struct
import wave
from io import BytesIO
from pathlib import Path


def split_wav_file(path: Path, *, chunk_ms: int = 400) -> tuple[int, list[bytes]]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if channels != 1 or sample_width != 2:
        # 非预期格式时整文件作为一块，避免破坏播放。
        return sample_rate, [path.read_bytes()]
    frame_bytes = sample_width * channels
    total_frames = len(frames) // frame_bytes
    frames_per_chunk = max(1, int(sample_rate * chunk_ms / 1000))
    chunks: list[bytes] = []
    offset = 0
    while offset < total_frames:
        count = min(frames_per_chunk, total_frames - offset)
        piece = frames[offset * frame_bytes : (offset + count) * frame_bytes]
        chunks.append(_pcm_to_wav(piece, sample_rate=sample_rate, channels=channels, sample_width=sample_width))
        offset += count
    if not chunks:
        chunks.append(_pcm_to_wav(b"", sample_rate=sample_rate, channels=channels, sample_width=sample_width))
    return sample_rate, chunks


def _pcm_to_wav(pcm: bytes, *, sample_rate: int, channels: int, sample_width: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def encode_wav_header_only(*, sample_rate: int, data_size: int) -> bytes:
    """预留：流式 PCM 首包可用。当前分块策略使用完整小 WAV。"""
    buffer = bytearray(44)
    buffer[0:4] = b"RIFF"
    struct.pack_into("<I", buffer, 4, 36 + data_size)
    buffer[8:12] = b"WAVE"
    buffer[12:16] = b"fmt "
    struct.pack_into("<IHHIIHH", buffer, 16, 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    buffer[36:40] = b"data"
    struct.pack_into("<I", buffer, 40, data_size)
    return bytes(buffer)
