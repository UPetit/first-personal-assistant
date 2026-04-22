from __future__ import annotations

import time
import pytest


@pytest.mark.asyncio
async def test_add_and_get_session(tmp_path):
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    event = {"type": "session_start", "session_id": "s1", "ts": "2026-01-01T00:00:00Z"}
    await store.add(event)

    results = await store.get_session("s1")
    assert len(results) == 1
    assert results[0]["type"] == "session_start"
    assert results[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_get_session_returns_only_matching_session(tmp_path):
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    await store.add({"type": "session_start", "session_id": "s1", "ts": "t"})
    await store.add({"type": "session_start", "session_id": "s2", "ts": "t"})
    await store.add({"type": "primary_done", "session_id": "s1", "ts": "t"})

    results = await store.get_session("s1")
    assert len(results) == 2
    assert all(e["session_id"] == "s1" for e in results)


@pytest.mark.asyncio
async def test_get_session_preserves_insertion_order(tmp_path):
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    types = ["session_start", "primary_start", "tool_call", "tool_result", "primary_done", "session_done"]
    for t in types:
        await store.add({"type": t, "session_id": "s1", "ts": "t"})

    results = await store.get_session("s1")
    assert [e["type"] for e in results] == types


@pytest.mark.asyncio
async def test_get_session_returns_empty_for_unknown(tmp_path):
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    assert await store.get_session("does_not_exist") == []


@pytest.mark.asyncio
async def test_cleanup_old_removes_stale_events(tmp_path):
    from kore.gateway.trace_store import TraceStore
    import aiosqlite

    store = TraceStore(tmp_path / "kore.db")
    await store._ensure_schema()

    db_path = tmp_path / "kore.db"
    old_ts = time.time() - 8 * 86400  # 8 days ago
    new_ts = time.time() - 1 * 86400  # 1 day ago

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO trace_events (session_id, type, data, ts) VALUES (?, ?, ?, ?)",
            ("s1", "session_start", '{"type":"session_start","session_id":"s1"}', old_ts),
        )
        await db.execute(
            "INSERT INTO trace_events (session_id, type, data, ts) VALUES (?, ?, ?, ?)",
            ("s2", "session_start", '{"type":"session_start","session_id":"s2"}', new_ts),
        )
        await db.commit()

    deleted = await store.cleanup_old(days=7)
    assert deleted == 1

    remaining = await store.get_session("s1")
    assert remaining == []
    kept = await store.get_session("s2")
    assert len(kept) == 1


@pytest.mark.asyncio
async def test_cleanup_old_returns_zero_when_nothing_to_prune(tmp_path):
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    await store.add({"type": "session_start", "session_id": "s1", "ts": "t"})
    deleted = await store.cleanup_old(days=7)
    assert deleted == 0


@pytest.mark.asyncio
async def test_schema_created_once(tmp_path, monkeypatch):
    """_ensure_schema skips aiosqlite after the first call."""
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    await store._ensure_schema()
    assert store._schema_created is True

    # Second call must be a no-op (no DB error even if DB were gone)
    await store._ensure_schema()
