from __future__ import annotations

import asyncio

from kore.channels.base import Message


class MessageQueue:
    """Thin asyncio.Queue wrapper for normalised inbound messages.

    All channels push Message objects here; the consumer loop in main.py
    reads from it and dispatches to the Orchestrator.
    """

    def __init__(self, maxsize: int = 0) -> None:
        self._q: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)

    async def put(self, message: Message) -> None:
        await self._q.put(message)

    async def get(self) -> Message:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()
