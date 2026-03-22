from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque


class WebSocketLogHandler(logging.Handler):
    """Logging handler that broadcasts formatted records to all WebSocket listeners.

    Thread-safe: ``emit()`` may be called from any thread (logging infrastructure
    makes no thread guarantees). Each listener queue is paired with its event loop
    so ``call_soon_threadsafe`` routes the put to the correct thread.

    - ``add_listener()`` returns a per-connection ``asyncio.Queue``.
    - ``recent(n)`` returns the last *n* buffered entries for late-joining clients.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=maxsize)
        # Maps queue → its owning event loop so emit() can cross thread boundaries.
        self._listeners: dict[asyncio.Queue[str], asyncio.AbstractEventLoop | None] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self._buffer.append(msg)
        with self._lock:
            snapshot = list(self._listeners.items())
        for q, loop in snapshot:
            try:
                if loop is not None and loop.is_running():
                    loop.call_soon_threadsafe(q.put_nowait, msg)
                else:
                    q.put_nowait(msg)
            except Exception:  # noqa: BLE001  — queue full or loop closed
                pass

    def add_listener(self, maxsize: int = 500) -> asyncio.Queue[str]:
        """Register a new listener queue.

        Safe to call from any context. When called from a running asyncio coroutine,
        the queue is paired with the running loop so ``emit()`` can use
        ``call_soon_threadsafe``. When called outside any loop (e.g. in tests),
        the loop is stored as ``None`` and ``emit()`` falls back to ``put_nowait``.
        """
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        with self._lock:
            self._listeners[q] = loop
        return q

    def remove_listener(self, q: asyncio.Queue[str]) -> None:
        with self._lock:
            self._listeners.pop(q, None)

    def recent(self, n: int = 100) -> list[str]:
        """Return last *n* buffered log entries."""
        entries = list(self._buffer)
        return entries[-n:]
