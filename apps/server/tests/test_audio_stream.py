import struct
import wave
from pathlib import Path

from app.modules.audio.domain.stream_schemas import AudioStarted, encode_audio_sse
from app.modules.audio.domain.wav_chunks import split_wav_file
import uuid


def _write_tone(path: Path, *, seconds: float = 1.0, rate: int = 24000) -> None:
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        # 简单非静音填充，避免全零被过度优化误判。
        payload = struct.pack("<" + "h" * frames, *([1000] * frames))
        handle.writeframes(payload)


def test_split_wav_into_playable_chunks(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    _write_tone(path, seconds=1.0)
    sample_rate, chunks = split_wav_file(path, chunk_ms=250)
    assert sample_rate == 24000
    assert len(chunks) >= 3
    for chunk in chunks:
        assert chunk[:4] == b"RIFF"
        assert b"WAVE" in chunk[:16]


def test_encode_audio_sse_shape() -> None:
    event = AudioStarted(
        task_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        sample_rate=24000,
        sequence=0,
    )
    frame = encode_audio_sse(event)
    assert "event: audio.started" in frame
    assert "data:" in frame
    assert frame.endswith("\n\n")
