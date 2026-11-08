import asyncio
from pathlib import Path

from audio_worker.backends.stub import StubAsrBackend, StubTtsBackend
from audio_worker.queue import InferenceQueue
from audio_worker.schemas import TtsRequest


def test_stub_asr_and_tts(tmp_path: Path) -> None:
    async def _run() -> None:
        asr = StubAsrBackend()
        await asr.load()
        result = await asr.recognize(b"RIFF" + b"\x00" * 40)
        assert result.backend == "stub"
        assert "stub" in result.text

        tts = StubTtsBackend(tmp_path)
        await tts.load()
        audio = await tts.synthesize(TtsRequest(text="你好，今天感觉怎么样？"))
        assert Path(audio.file_path).exists()
        assert audio.sample_rate == 24000
        assert audio.duration_ms > 0

    asyncio.run(_run())


def test_inference_queue_serializes() -> None:
    async def _run() -> None:
        queue = InferenceQueue(maxsize=2)
        order: list[int] = []

        async def job(value: int) -> int:
            order.append(value)
            await asyncio.sleep(0.01)
            return value

        first, second = await asyncio.gather(queue.run(lambda: job(1)), queue.run(lambda: job(2)))
        assert {first, second} == {1, 2}
        assert order == [1, 2] or order == [1, 2]

    asyncio.run(_run())
