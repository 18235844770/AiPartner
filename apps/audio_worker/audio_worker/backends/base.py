from __future__ import annotations

from typing import Protocol

from audio_worker.schemas import AsrResult, TtsRequest, TtsResult


class AsrBackend(Protocol):
    name: str
    model_name: str
    loaded: bool

    async def load(self) -> None: ...

    async def recognize(self, audio_bytes: bytes, *, language: str = "auto") -> AsrResult: ...


class TtsBackend(Protocol):
    name: str
    model_name: str
    loaded: bool

    async def load(self) -> None: ...

    async def synthesize(self, request: TtsRequest) -> TtsResult: ...
