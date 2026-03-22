from __future__ import annotations

import math
import time
from dataclasses import dataclass

from kore.memory.embeddings import EmbeddingModel
from kore.memory.event_log import EventLog, MemoryEvent


@dataclass
class RetrievalResult:
    event: MemoryEvent
    score: float


def temporal_decay(score: float, event_timestamp: float, half_life_days: float = 60.0) -> float:
    """Apply exponential temporal decay to a score.

    Score halves every *half_life_days* days. A 60-day half-life means an event
    from 60 days ago contributes half as much as an event from today.
    """
    age_seconds = time.time() - event_timestamp
    age_days = max(age_seconds / 86400.0, 0.0)
    return score * math.exp(-math.log(2) * age_days / half_life_days)


def fuse_scores(
    bm25_results: list[tuple[int, float]],
    vec_results: list[tuple[int, float]],
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> dict[int, float]:
    """Fuse BM25 and vector scores into a single score per event_id.

    BM25 ranks are negative FTS5 values (closer to 0 = better).
    Vector distances are non-negative (0 = identical, higher = less similar).
    Both are normalized to [0, 1] before weighting.
    """
    scores: dict[int, float] = {}

    if bm25_results:
        # FTS5 rank: closer to 0 = better (e.g. -1.0 is better than -5.0).
        # Normalize: best (closest to 0, i.e. max value) → 1.0, worst → 0.0
        min_rank = min(r for _, r in bm25_results)  # most negative (worst)
        max_rank = max(r for _, r in bm25_results)  # closest to 0 (best)
        span = max_rank - min_rank  # always >= 0
        for event_id, rank in bm25_results:
            if span == 0.0:
                normalized = 1.0  # all equally ranked — give full score
            else:
                normalized = (rank - min_rank) / span  # closest to 0 → 1.0
            scores[event_id] = scores.get(event_id, 0.0) + bm25_weight * normalized

    if vec_results:
        # Distance: 0 = identical. Normalize: closest → 1.0, farthest → 0.0
        max_dist = max(d for _, d in vec_results) or 1.0
        for event_id, dist in vec_results:
            similarity = 1.0 - (dist / max_dist)
            scores[event_id] = scores.get(event_id, 0.0) + vector_weight * similarity

    return scores


class Retriever:
    """Hybrid retriever combining BM25 and vector search with temporal decay."""

    def __init__(
        self,
        event_log: EventLog,
        embedding_model: EmbeddingModel,
        top_k: int = 10,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        decay_half_life_days: float = 60.0,
        min_score: float = 0.0,
    ) -> None:
        self._log = event_log
        self._em = embedding_model
        self._top_k = top_k
        self._vector_weight = vector_weight
        self._bm25_weight = bm25_weight
        self._half_life = decay_half_life_days
        self._min_score = min_score

    async def search(self, query: str) -> list[RetrievalResult]:
        """Run hybrid BM25 + vector search, apply temporal decay, return top-K results."""
        fetch_k = self._top_k * 3  # over-fetch before decay ranking

        # BM25 search (always available)
        bm25_events = await self._log.bm25_search(query, top_k=fetch_k)
        event_map: dict[int, MemoryEvent] = {}
        for ev in bm25_events:
            event_map[ev.id] = ev

        # Re-fetch with raw rank scores
        bm25_scored = await self._log.bm25_search_with_rank(query, top_k=fetch_k)
        bm25_pairs: list[tuple[int, float]] = [(eid, rank) for eid, rank in bm25_scored]

        # Vector search (only if embedding available)
        vec_pairs: list[tuple[int, float]] = []
        query_embedding = await self._em.embed(query)
        if query_embedding is not None:
            vec_pairs = await self._log.vec_search(query_embedding, top_k=fetch_k)
            # Fill in event_map for vec-only hits
            vec_event_ids = {eid for eid, _ in vec_pairs if eid not in event_map}
            if vec_event_ids:
                extra = await self._log.get_by_ids(list(vec_event_ids))
                for ev in extra:
                    event_map[ev.id] = ev

        # Fuse scores
        raw_scores = fuse_scores(bm25_pairs, vec_pairs, self._vector_weight, self._bm25_weight)

        # Apply temporal decay
        decayed: list[RetrievalResult] = []
        for event_id, score in raw_scores.items():
            if event_id not in event_map:
                continue
            ev = event_map[event_id]
            final_score = temporal_decay(score, ev.timestamp, self._half_life)
            decayed.append(RetrievalResult(event=ev, score=final_score))

        # Sort, filter by min_score, and top-K
        decayed.sort(key=lambda r: r.score, reverse=True)
        if self._min_score > 0.0:
            decayed = [r for r in decayed if r.score >= self._min_score]
        return decayed[: self._top_k]
