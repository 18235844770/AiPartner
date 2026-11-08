"""TTS 单队列：同一时刻只跑一个合成任务。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class InferenceQueue:
    def __init__(self, maxsize: int = 8) -> None:
        self._lock = asyncio.Lock()
        self._depth = 0
        self._maxsize = maxsize

    @property
    def depth(self) -> int:
        return self._depth

    async def run(self, work: Callable[[], Awaitable[T]]) -> T:
        if self._depth >= self._maxsize:
            raise RuntimeError("推理队列已满")
        self._depth += 1
        try:
            async with self._lock:
                return await work()
        finally:
            self._depth -= 1
