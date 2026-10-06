"""Priority queue that serializes GPU work (section 3.2).

All GPU jobs run one at a time on a single worker thread. Lower priority number
runs first; jobs with the same priority run FIFO. Long low-priority work (e.g.
pronunciation analysis) must be submitted in small chunks so a turn's
transcription never waits behind it for long.
"""

import asyncio
import itertools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum
from typing import Any, TypeVar

T = TypeVar("T")


class Priority(IntEnum):
    HIGH = 0  # transcription — end of turn and barge-in decisions wait on it
    TTS = 5  # interviewer speech — also blocks the conversation, but a barge-in check
    #          must never queue behind the sentences of the reply being interrupted
    LOW = 10  # pronunciation analysis — background, between turns


class GpuQueue:
    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def submit(self, priority: Priority, fn: Callable[..., T], *args: Any) -> T:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((int(priority), next(self._seq), fn, args, future))
        return await future

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            _, _, fn, args, future = await self._queue.get()
            if future.cancelled():  # caller went away (e.g. barge-in cancelled the TTS)
                continue
            try:
                result = await loop.run_in_executor(self._executor, fn, *args)
            except Exception as exc:  # noqa: BLE001 — forwarded to the caller
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)
