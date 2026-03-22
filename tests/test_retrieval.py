from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_temporal_decay_recent_event():
    from kore.memory.retrieval import temporal_decay
    # Recent event (0 days old) should have decay ≈ 1.0
    decay = temporal_decay(1.0, time.time(), half_life_days=60)
    assert abs(decay - 1.0) < 0.01


def test_temporal_decay_half_life():
    from kore.memory.retrieval import temporal_decay
    # At exactly half-life, score should halve
    ts = time.time() - (60 * 86400)  # 60 days ago
    decay = temporal_decay(1.0, ts, half_life_days=60)
    assert abs(decay - 0.5) < 0.01


def test_temporal_decay_very_old():
    from kore.memory.retrieval import temporal_decay
    ts = time.time() - (365 * 86400)  # 1 year ago
    decay = temporal_decay(1.0, ts, half_life_days=60)
    assert decay < 0.05


def test_fuse_scores_vector_only():
    from kore.memory.retrieval import fuse_scores
    vec = [(1, 0.0), (2, 0.5)]  # id, distance (lower = better)
    bm25 = []
    fused = fuse_scores(bm25, vec, vector_weight=0.7, bm25_weight=0.3)
    # Event 1 (distance 0) should score higher than Event 2 (distance 0.5)
    assert fused[1] > fused[2]


def test_fuse_scores_bm25_only():
    from kore.memory.retrieval import fuse_scores
    bm25 = [(1, -1.0), (2, -5.0)]  # id, rank (closer to 0 = better)
    vec = []
    fused = fuse_scores(bm25, vec, vector_weight=0.7, bm25_weight=0.3)
    assert fused[1] > fused[2]


def test_fuse_scores_both():
    from kore.memory.retrieval import fuse_scores
    # Event 1: good BM25, ok vector; Event 2: poor BM25, ok vector
    bm25 = [(1, -0.5), (2, -3.0)]
    vec = [(1, 0.2), (2, 0.3)]
    fused = fuse_scores(bm25, vec, vector_weight=0.7, bm25_weight=0.3)
    assert fused[1] > fused[2]


@pytest.mark.asyncio
async def test_retriever_returns_top_k(tmp_path):
    from kore.db.database import create_engine, setup_schema
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog
    from kore.memory.retrieval import Retriever

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)  # BM25-only
    event_log = EventLog(engine, mock_em)

    for i in range(5):
        await event_log.insert(category="fact", content=f"python fact number {i}", source="user")

    retriever = Retriever(event_log, mock_em, top_k=3, vector_weight=0.7, bm25_weight=0.3, decay_half_life_days=60)
    results = await retriever.search("python")
    assert len(results) <= 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_retriever_applies_temporal_decay(tmp_path):
    """Older events score lower than recent ones given identical content."""
    from kore.db.database import create_engine, setup_schema
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog
    from kore.memory.retrieval import Retriever

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)
    event_log = EventLog(engine, mock_em)

    old_ts = time.time() - (200 * 86400)  # 200 days ago
    await event_log.insert_with_timestamp("fact", "python tip old", "user", 0.5, old_ts)
    await event_log.insert("fact", "python tip recent", "user")

    retriever = Retriever(event_log, mock_em, top_k=10, vector_weight=0.7, bm25_weight=0.3, decay_half_life_days=60)
    results = await retriever.search("python tip")

    assert len(results) >= 2
    # Recent event should appear before old event
    contents = [r.event.content for r in results]
    recent_idx = next(i for i, r in enumerate(results) if "recent" in r.event.content)
    old_idx = next(i for i, r in enumerate(results) if "old" in r.event.content)
    assert recent_idx < old_idx

    await engine.dispose()
