from __future__ import annotations

import base64
import json
import wave
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path


async def iter_wav_ndjson(file_path: str, *, sample_rate: int, chunk_ms: int = 400) -> AsyncIterator[str]:
    path = Path(file_path)
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate() or sample_rate
        pcm = handle.readframes(handle.getnframes())
    frame_bytes = max(1, channels * width)
    total = len(pcm) // frame_bytes
    step = max(1, int(rate * chunk_ms / 1000))
    index = 0
    offset = 0
    while offset < total:
        count = min(step, total - offset)
        piece = pcm[offset * frame_bytes : (offset + count) * frame_bytes]
        blob = _pcm_wav(piece, rate=rate, channels=channels, width=width)
        payload = {
            "chunk_index": index,
            "sample_rate": rate,
            "format": "wav",
            "is_last": offset + count >= total,
            "data_base64": base64.b64encode(blob).decode("ascii"),
        }
        yield json.dumps(payload, ensure_ascii=False) + "\n"
        index += 1
        offset += count


def _pcm_wav(pcm: bytes, *, rate: int, channels: int, width: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buffer.getvalue()
