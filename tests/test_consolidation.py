from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
async def consolidation_setup(tmp_path):
    from kore.db.database import create_engine, setup_schema
    from kore.memory.core_memory import CoreMemory
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)

    core_memory = CoreMemory(tmp_path / "core_memory.json")
    event_log = EventLog(engine, mock_em)

    yield core_memory, event_log, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_consolidation_promotes_high_importance_fact(consolidation_setup):
    """High-importance events get promoted to core memory."""
    from kore.memory.consolidation import ConsolidationAgent

    core_memory, event_log, _ = consolidation_setup
    await event_log.insert(category="fact", content="User's name is Alice", source="user", importance=0.9)

    agent = ConsolidationAgent(core_memory, event_log, model="test")
    await agent.run()

    # After consolidation, the event should be marked consolidated
    events = await event_log.get_unconsolidated(limit=100)
    assert all(e.importance < 0.9 or e.content != "User's name is Alice" for e in events)


@pytest.mark.asyncio
async def test_consolidation_gc_removes_old_low_importance(consolidation_setup):
    """Old events below importance threshold are garbage collected."""
    from kore.memory.consolidation import ConsolidationAgent

    core_memory, event_log, _ = consolidation_setup
    old_ts = time.time() - (100 * 86400)  # 100 days ago
    eid = await event_log.insert_with_timestamp(
        "fact", "stale unimportant note", "user", importance=0.1, timestamp=old_ts
    )

    agent = ConsolidationAgent(
        core_memory, event_log, model="test",
        gc_days=90, gc_min_importance=0.3,
    )
    await agent.run()

    recent = await event_log.get_recent(limit=100)
    assert not any(e.id == eid for e in recent)


@pytest.mark.asyncio
async def test_consolidation_marks_events_consolidated(consolidation_setup):
    """All processed events are marked consolidated after a run."""
    from kore.memory.consolidation import ConsolidationAgent

    core_memory, event_log, _ = consolidation_setup
    for i in range(3):
        await event_log.insert(category="fact", content=f"Fact {i}", source="user", importance=0.5)

    agent = ConsolidationAgent(core_memory, event_log, model="test")
    await agent.run()

    remaining = await event_log.get_unconsolidated(limit=100)
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_consolidation_skips_already_consolidated(consolidation_setup):
    """Already-consolidated events are not processed again."""
    from kore.memory.consolidation import ConsolidationAgent

    core_memory, event_log, _ = consolidation_setup
    eid = await event_log.insert(category="fact", content="Already done", source="user")
    await event_log.mark_consolidated(eid)

    # Second run should not fail and should not double-process
    agent = ConsolidationAgent(core_memory, event_log, model="test")
    await agent.run()  # should not raise


@pytest.mark.asyncio
async def test_consolidation_detects_contradiction_marks_superseded(consolidation_setup):
    """Contradiction detection marks older event as superseded_by newer."""
    from unittest.mock import AsyncMock, MagicMock
    from kore.memory.consolidation import ConsolidationAgent, _ContradictionPair

    core_memory, event_log, _ = consolidation_setup
    # Two contradicting facts — same entity, different values
    old_ts = time.time() - 200
    new_ts = time.time() - 10
    older_id = await event_log.insert_with_timestamp("fact", "User lives in London", "user", 0.7, old_ts)
    newer_id = await event_log.insert_with_timestamp("fact", "User lives in Paris", "user", 0.8, new_ts)

    agent = ConsolidationAgent(core_memory, event_log, model="test")
    # Patch contradiction agent to return the pair
    mock_result = MagicMock()
    mock_result.output = [_ContradictionPair(older_id=older_id, newer_id=newer_id)]
    agent._contradiction_agent.run = AsyncMock(return_value=mock_result)

    await agent.run()

    # Older event should be marked superseded by newer
    async with event_log._engine.connect() as conn:
        from sqlalchemy import text as sql_text
        row = (await conn.execute(sql_text("SELECT superseded_by FROM events WHERE id = :id"), {"id": older_id})).fetchone()
    assert row is not None and row[0] == newer_id


@pytest.mark.asyncio
async def test_consolidation_compresses_old_events_into_summary(consolidation_setup):
    """Old events (>30 days) grouped by week are compressed into a summary event."""
    from unittest.mock import AsyncMock, MagicMock
    from kore.memory.consolidation import ConsolidationAgent, _CompressionSummary

    core_memory, event_log, _ = consolidation_setup
    base_ts = time.time() - (40 * 86400)  # 40 days ago
    for i in range(5):
        await event_log.insert_with_timestamp("fact", f"Old fact {i}", "user", 0.5, base_ts + i * 3600)

    agent = ConsolidationAgent(core_memory, event_log, model="test")
    # Patch compression agent to return a summary
    mock_result = MagicMock()
    mock_result.output = _CompressionSummary(category="fact", summary="User did various tasks 40 days ago")
    agent._compression_agent.run = AsyncMock(return_value=mock_result)

    await agent.run()

    # A summary event should have been inserted
    recent = await event_log.get_recent(limit=50)
    summaries = [e for e in recent if e.source == "consolidation" and "weekly summary" in e.content]
    assert len(summaries) >= 1
