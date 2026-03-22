from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class TraceStore:
    """Persist session trace events to SQLite with automatic TTL cleanup.

    Events are stored as JSON blobs in the ``trace_events`` table which is
    created on first use — no migration step required.

    Call ``cleanup_old()`` at startup to prune rows older than N days and
    prevent unbounded DB growth.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS trace_events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT    NOT NULL,
        type       TEXT    NOT NULL,
        data       TEXT    NOT NULL,
        ts         REAL    NOT NULL
    )"""
    _IDX = "CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_events(session_id)"

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._schema_created = False

    async def _ensure_schema(self) -> None:
        if self._schema_created:
            return
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(self._DDL)
            await db.execute(self._IDX)
            await db.commit()
        self._schema_created = True

    async def add(self, event: dict) -> None:
        """Persist a trace event dict."""
        await self._ensure_schema()
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO trace_events (session_id, type, data, ts) VALUES (?, ?, ?, ?)",
                (
                    event.get("session_id", ""),
                    event.get("type", ""),
                    json.dumps(event),
                    time.time(),
                ),
            )
            await db.commit()

    async def get_session(self, session_id: str) -> list[dict]:
        """Return all trace events for a session ordered by insertion."""
        await self._ensure_schema()
        import aiosqlite
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT data FROM trace_events WHERE session_id = ? ORDER BY id",
                (session_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def cleanup_old(self, days: int = 7) -> int:
        """Delete events older than ``days`` days. Returns number of rows deleted."""
        await self._ensure_schema()
        import aiosqlite
        cutoff = time.time() - days * 86400
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM trace_events WHERE ts < ?", (cutoff,)
            )
            await db.commit()
            deleted = cursor.rowcount
        if deleted:
            logger.info("TraceStore: pruned %d events older than %d days", deleted, days)
        return deleted
