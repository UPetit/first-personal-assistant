from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
async def engine(tmp_path):
    from kore.db.database import create_engine, setup_schema
    e = create_engine(tmp_path / "test.db")
    await setup_schema(e)
    yield e
    await e.dispose()


@pytest.fixture
async def event_log(engine):
    from kore.memory.event_log import EventLog
    from kore.memory.embeddings import EmbeddingModel
    # Mock embedding model that returns fixed 384-dim vector
    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)  # BM25-only in tests
    return EventLog(engine, mock_em)


@pytest.mark.asyncio
async def test_event_log_insert_returns_id(event_log):
    event_id = await event_log.insert(
        category="fact",
        content="The sky is blue",
        source="user",
        importance=0.8,
    )
    assert isinstance(event_id, int)
    assert event_id > 0


@pytest.mark.asyncio
async def test_event_log_insert_multiple(event_log):
    ids = []
    for i in range(3):
        eid = await event_log.insert(
            category="fact",
            content=f"Fact number {i}",
            source="assistant",
            importance=0.5,
        )
        ids.append(eid)
    assert len(set(ids)) == 3  # all unique


@pytest.mark.asyncio
async def test_event_log_fts_search_finds_content(event_log):
    await event_log.insert(category="fact", content="Python is a programming language", source="user")
    await event_log.insert(category="fact", content="The weather is sunny today", source="user")

    results = await event_log.bm25_search("Python programming", top_k=5)
    assert len(results) >= 1
    assert any("Python" in r.content for r in results)


@pytest.mark.asyncio
async def test_event_log_fts_search_no_match(event_log):
    await event_log.insert(category="fact", content="Alice likes cats", source="user")
    results = await event_log.bm25_search("quantum physics", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_event_log_get_recent(event_log):
    for i in range(5):
        await event_log.insert(category="fact", content=f"Event {i}", source="user")
    recent = await event_log.get_recent(limit=3)
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_event_log_mark_consolidated(event_log):
    eid = await event_log.insert(category="fact", content="some fact", source="user")
    await event_log.mark_consolidated(eid)
    events = await event_log.get_unconsolidated(limit=100)
    assert not any(e.id == eid for e in events)


@pytest.mark.asyncio
async def test_event_log_mark_superseded(event_log):
    old_id = await event_log.insert(category="fact", content="old fact", source="user")
    new_id = await event_log.insert(category="fact", content="new fact", source="user")
    await event_log.mark_superseded(old_id, superseded_by=new_id)

    events = await event_log.get_active(limit=100)
    assert not any(e.id == old_id for e in events)
    assert any(e.id == new_id for e in events)


@pytest.mark.asyncio
async def test_event_log_get_old_low_importance(event_log):
    """Events with age > gc_days and importance < threshold should be retrievable for GC."""
    import time
    old_ts = time.time() - (100 * 86400)  # 100 days ago
    eid = await event_log.insert_with_timestamp(
        category="fact", content="old unimportant", source="user",
        importance=0.1, timestamp=old_ts,
    )
    candidates = await event_log.get_gc_candidates(min_age_days=90, max_importance=0.3)
    assert any(e.id == eid for e in candidates)
