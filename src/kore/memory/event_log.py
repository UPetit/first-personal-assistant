from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kore.memory.embeddings import EmbeddingModel, deserialize_vector, serialize_vector


@dataclass
class MemoryEvent:
    """In-memory representation of a row in the events table."""

    id: int
    timestamp: float
    category: str
    content: str
    source: str | None = None
    importance: float = 0.5
    embedding: list[float] | None = None
    consolidated: bool = False
    superseded_by: int | None = None


class EventLog:
    """Layer 2 memory: append-only SQLite event store with FTS5 and sqlite-vec search.

    All write methods embed content automatically (if the embedding model is available)
    and insert into both the ``events`` table and the ``event_embeddings`` vec table.
    """

    def __init__(self, engine: AsyncEngine, embedding_model: EmbeddingModel) -> None:
        self._engine = engine
        self._em = embedding_model

    # ── write ─────────────────────────────────────────────────────────────────

    async def insert(
        self,
        category: str,
        content: str,
        source: str | None = None,
        importance: float = 0.5,
    ) -> int:
        """Insert a new event. Returns the new row id."""
        return await self.insert_with_timestamp(
            category=category,
            content=content,
            source=source,
            importance=importance,
            timestamp=time.time(),
        )

    async def insert_with_timestamp(
        self,
        category: str,
        content: str,
        source: str | None,
        importance: float,
        timestamp: float,
    ) -> int:
        """Insert with an explicit timestamp (for testing and backfill)."""
        embedding_bytes: bytes | None = None
        embedding_list = await self._em.embed(content)
        if embedding_list is not None:
            embedding_bytes = serialize_vector(embedding_list)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO events (timestamp, category, content, source, importance, embedding) "
                    "VALUES (:ts, :cat, :content, :source, :imp, :emb)"
                ),
                {
                    "ts": timestamp,
                    "cat": category,
                    "content": content,
                    "source": source,
                    "imp": importance,
                    "emb": embedding_bytes,
                },
            )
            event_id: int = result.lastrowid  # type: ignore[assignment]

            # Insert into vec table if embedding is available
            if embedding_bytes is not None:
                try:
                    await conn.execute(
                        text("INSERT INTO event_embeddings (event_id, embedding) VALUES (:id, :emb)"),
                        {"id": event_id, "emb": embedding_bytes},
                    )
                except Exception:
                    pass  # vec table may not exist (no sqlite-vec)

        return event_id

    async def mark_consolidated(self, event_id: int) -> None:
        """Mark event as consolidated (included in Layer 3 pass)."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE events SET consolidated = 1 WHERE id = :id"),
                {"id": event_id},
            )

    async def mark_superseded(self, event_id: int, superseded_by: int) -> None:
        """Mark event as superseded by a newer event."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE events SET superseded_by = :new_id WHERE id = :id"),
                {"new_id": superseded_by, "id": event_id},
            )

    # ── read ──────────────────────────────────────────────────────────────────

    async def bm25_search(self, query: str, top_k: int = 10) -> list[MemoryEvent]:
        """BM25 keyword search via FTS5. Returns events ranked by relevance."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT e.id, e.timestamp, e.category, e.content, e.source, "
                    "       e.importance, e.embedding, e.consolidated, e.superseded_by "
                    "FROM events_fts f "
                    "JOIN events e ON e.id = f.rowid "
                    "WHERE events_fts MATCH :q AND e.superseded_by IS NULL "
                    "ORDER BY f.rank "
                    "LIMIT :k"
                ),
                {"q": query, "k": top_k},
            )
            return [_row_to_event(r) for r in rows.fetchall()]

    async def vec_search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[int, float]]:
        """Vector cosine search via sqlite-vec. Returns list of (event_id, distance)."""
        emb_bytes = serialize_vector(query_embedding)
        try:
            async with self._engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT event_id, distance FROM event_embeddings "
                        "WHERE embedding MATCH :emb AND k = :k "
                        "ORDER BY distance"
                    ),
                    {"emb": emb_bytes, "k": top_k},
                )
                return [(r[0], r[1]) for r in rows.fetchall()]
        except Exception:
            return []  # vec table unavailable

    async def get_recent(self, limit: int = 20) -> list[MemoryEvent]:
        """Return the most recently inserted events."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, timestamp, category, content, source, importance, "
                    "       embedding, consolidated, superseded_by "
                    "FROM events ORDER BY timestamp DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
            return [_row_to_event(r) for r in rows.fetchall()]

    async def get_unconsolidated(self, limit: int = 100) -> list[MemoryEvent]:
        """Return events not yet processed by the consolidation agent."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, timestamp, category, content, source, importance, "
                    "       embedding, consolidated, superseded_by "
                    "FROM events WHERE consolidated = 0 AND superseded_by IS NULL "
                    "ORDER BY timestamp ASC LIMIT :lim"
                ),
                {"lim": limit},
            )
            return [_row_to_event(r) for r in rows.fetchall()]

    async def get_active(self, limit: int = 100) -> list[MemoryEvent]:
        """Return events that are not superseded."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, timestamp, category, content, source, importance, "
                    "       embedding, consolidated, superseded_by "
                    "FROM events WHERE superseded_by IS NULL "
                    "ORDER BY timestamp DESC LIMIT :lim"
                ),
                {"lim": limit},
            )
            return [_row_to_event(r) for r in rows.fetchall()]

    async def get_gc_candidates(self, min_age_days: int, max_importance: float) -> list[MemoryEvent]:
        """Return old, low-importance events that are candidates for garbage collection."""
        cutoff_ts = time.time() - (min_age_days * 86400)
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, timestamp, category, content, source, importance, "
                    "       embedding, consolidated, superseded_by "
                    "FROM events "
                    "WHERE timestamp < :cutoff AND importance < :max_imp "
                    "AND superseded_by IS NULL "
                    "ORDER BY importance ASC"
                ),
                {"cutoff": cutoff_ts, "max_imp": max_importance},
            )
            return [_row_to_event(r) for r in rows.fetchall()]

    async def delete_event(self, event_id: int) -> None:
        """Hard-delete an event (used by GC)."""
        async with self._engine.begin() as conn:
            await conn.execute(text("DELETE FROM events WHERE id = :id"), {"id": event_id})

    async def get_events_older_than(self, days: int, limit: int = 200) -> list[MemoryEvent]:
        """Fetch unconsolidated events older than `days` days (for compression)."""
        cutoff = time.time() - days * 86400
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, timestamp, category, content, source, importance, "
                    "embedding, consolidated, superseded_by FROM events "
                    "WHERE timestamp < :cutoff AND consolidated = 0 AND superseded_by IS NULL "
                    "ORDER BY timestamp ASC LIMIT :limit"
                ),
                {"cutoff": cutoff, "limit": limit},
            )
            return [_row_to_event(r) for r in rows.fetchall()]

    async def bm25_search_with_rank(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """BM25 search returning (event_id, fts5_rank) pairs."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT f.rowid, f.rank FROM events_fts f "
                    "JOIN events e ON e.id = f.rowid "
                    "WHERE events_fts MATCH :q AND e.superseded_by IS NULL "
                    "ORDER BY f.rank LIMIT :k"
                ),
                {"q": query, "k": top_k},
            )
            return [(r[0], r[1]) for r in rows.fetchall()]

    async def get_by_ids(self, ids: list[int]) -> list[MemoryEvent]:
        """Fetch events by a list of IDs."""
        if not ids:
            return []
        placeholders = ",".join(f":id{i}" for i in range(len(ids)))
        params = {f"id{i}": v for i, v in enumerate(ids)}
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"SELECT id, timestamp, category, content, source, importance, "
                    f"embedding, consolidated, superseded_by "
                    f"FROM events WHERE id IN ({placeholders})"
                ),
                params,
            )
            return [_row_to_event(r) for r in rows.fetchall()]


def _row_to_event(row: Any) -> MemoryEvent:
    emb = None
    if row[6] is not None:
        try:
            emb = deserialize_vector(row[6])
        except Exception:
            pass
    return MemoryEvent(
        id=row[0],
        timestamp=row[1],
        category=row[2],
        content=row[3],
        source=row[4],
        importance=row[5] or 0.5,
        embedding=emb,
        consolidated=bool(row[7]),
        superseded_by=row[8],
    )
