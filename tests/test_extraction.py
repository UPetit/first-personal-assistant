from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.models.test import TestModel


@pytest.fixture
async def extraction_setup(tmp_path):
    from kore.db.database import create_engine, setup_schema
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)
    event_log = EventLog(engine, mock_em)

    yield event_log, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_extract_from_conversation_stores_events(extraction_setup):
    """Extraction runs and stores at least one event per non-empty conversation."""
    from kore.llm.types import KoreMessage
    from kore.memory.extraction import ExtractionAgent

    event_log, _ = extraction_setup
    agent = ExtractionAgent(event_log, model="test")

    conversation = [
        KoreMessage(role="user", content="My name is Alice and I work at Acme Corp."),
        KoreMessage(role="assistant", content="Nice to meet you, Alice!"),
    ]

    count_before = len(await event_log.get_recent(limit=100))
    await agent.extract_and_store(conversation)
    count_after = len(await event_log.get_recent(limit=100))

    assert count_after > count_before


@pytest.mark.asyncio
async def test_extract_empty_conversation_stores_nothing(extraction_setup):
    """Empty conversation should not store any events."""
    from kore.memory.extraction import ExtractionAgent

    event_log, _ = extraction_setup
    agent = ExtractionAgent(event_log, model="test")

    count_before = len(await event_log.get_recent(limit=100))
    await agent.extract_and_store([])
    count_after = len(await event_log.get_recent(limit=100))

    assert count_after == count_before


@pytest.mark.asyncio
async def test_extract_stores_with_importance(extraction_setup):
    """Extracted events have importance scores in 0-1 range."""
    from kore.llm.types import KoreMessage
    from kore.memory.extraction import ExtractionAgent

    event_log, _ = extraction_setup
    agent = ExtractionAgent(event_log, model="test")

    conversation = [
        KoreMessage(role="user", content="I prefer dark mode and I hate Comic Sans."),
        KoreMessage(role="assistant", content="Noted!"),
    ]
    await agent.extract_and_store(conversation)

    events = await event_log.get_recent(limit=10)
    for ev in events:
        assert 0.0 <= ev.importance <= 1.0
