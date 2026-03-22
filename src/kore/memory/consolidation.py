from __future__ import annotations

import logging
import time

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from kore.memory.core_memory import CoreMemory, TokenCapExceeded
from kore.memory.event_log import EventLog, MemoryEvent

logger = logging.getLogger(__name__)

_PROMOTION_PROMPT = """
You are a memory consolidation agent. Given a list of recent memory events,
decide which facts are durable enough to promote to always-in-context core memory.

For each fact worth promoting, output a JSON object with:
  { "path": "dot.notation.path", "value": <value> }

Promote only facts that:
- Are likely to remain true across many future conversations
- Are user-specific (name, preferences, ongoing projects, rules)
- Are NOT ephemeral (temporary tasks, one-off requests)

Return a JSON array. Return [] if nothing is worth promoting.
""".strip()

_CONTRADICTION_PROMPT = """
You are detecting contradictory facts in a memory system.
Given a list of memory events (each with an id, category, and content),
identify pairs of events that state conflicting facts about the same entity.

For each contradicting pair, output:
  { "older_id": <id of stale/incorrect event>, "newer_id": <id of correct/newer event> }

Newer wins (higher timestamp is newer). Return a JSON array. Return [] if no contradictions found.
""".strip()

_COMPRESSION_PROMPT = """
You are compressing old memory events into a concise weekly summary.
Given a list of memory events from the same week, write a single summary capturing key information.

Output a JSON object:
  { "category": "<most common category>", "summary": "<concise summary of key facts>" }
""".strip()


class _PromotionItem(BaseModel):
    path: str
    value: object


class _ContradictionPair(BaseModel):
    older_id: int
    newer_id: int


class _CompressionSummary(BaseModel):
    category: str
    summary: str


class ConsolidationAgent:
    """Layer 3 memory: background agent that processes unconsolidated events.

    On each run:
    1. Detects contradictions between events → marks older as superseded_by newer
    2. Promotes durable facts to core memory (via LLM)
    3. Marks all fetched events as consolidated
    4. Compresses old events (>30 days) into weekly summaries
    5. Garbage-collects stale low-importance events

    Scheduled every 30 minutes (timer wired in Phase 5).
    """

    def __init__(
        self,
        core_memory: CoreMemory,
        event_log: EventLog,
        model: str = "anthropic:claude-haiku-4-5-20251001",
        gc_days: int = 90,
        gc_min_importance: float = 0.3,
        compress_after_days: int = 30,
    ) -> None:
        self._core_memory = core_memory
        self._event_log = event_log
        self._gc_days = gc_days
        self._gc_min_importance = gc_min_importance
        self._compress_after_days = compress_after_days
        _model = TestModel() if model == "test" else model
        self._agent: Agent = Agent(_model, system_prompt=_PROMOTION_PROMPT, output_type=list[_PromotionItem])
        self._contradiction_agent: Agent = Agent(_model, system_prompt=_CONTRADICTION_PROMPT, output_type=list[_ContradictionPair])
        self._compression_agent: Agent = Agent(_model, system_prompt=_COMPRESSION_PROMPT, output_type=_CompressionSummary)

    async def run(self) -> None:
        """Run one consolidation cycle."""
        # Compress old events first (before marking consolidated)
        await self._compress_old_events()

        events = await self._event_log.get_unconsolidated(limit=100)
        if events:
            await self._detect_contradictions(events)
            await self._promote(events)
            for ev in events:
                await self._event_log.mark_consolidated(ev.id)

        await self._garbage_collect()

    async def _detect_contradictions(self, events: list[MemoryEvent]) -> None:
        """Find contradicting pairs; mark older event as superseded_by newer."""
        if len(events) < 2:
            return
        text = "\n".join(
            f"[id={ev.id}] [{ev.category}] (ts={ev.timestamp:.0f}): {ev.content}"
            for ev in events
        )
        try:
            result = await self._contradiction_agent.run(
                f"Find contradictions in these memory events:\n\n{text}"
            )
            pairs: list[_ContradictionPair] = result.output or []
        except Exception as exc:
            logger.warning("Contradiction detection failed: %s", exc)
            return
        for pair in pairs:
            try:
                await self._event_log.mark_superseded(pair.older_id, pair.newer_id)
                logger.info("Contradiction: event %d superseded by %d", pair.older_id, pair.newer_id)
            except Exception as exc:
                logger.warning("Failed to mark contradiction %d→%d: %s", pair.older_id, pair.newer_id, exc)

    async def _promote(self, events: list[MemoryEvent]) -> None:
        """Ask the LLM which facts to promote to core memory."""
        text = "\n".join(
            f"[{ev.category}] (importance={ev.importance:.2f}): {ev.content}"
            for ev in events
        )
        try:
            result = await self._agent.run(
                f"Consolidate these memory events into core memory facts:\n\n{text}"
            )
            items: list[_PromotionItem] = result.output or []
        except Exception as exc:
            logger.warning("Consolidation LLM call failed: %s", exc)
            return
        for item in items:
            try:
                self._core_memory.update(item.path, item.value)
                logger.info("Promoted to core memory: %s = %r", item.path, item.value)
            except TokenCapExceeded:
                logger.warning("Core memory cap reached; skipping %s", item.path)
            except Exception as exc:
                logger.warning("Failed to promote %s: %s", item.path, exc)

    async def _compress_old_events(self) -> None:
        """Compress events older than compress_after_days into weekly summaries."""
        old_events = await self._event_log.get_events_older_than(days=self._compress_after_days, limit=200)
        if len(old_events) < 5:
            return
        # Group by calendar week
        week_seconds = 7 * 86400
        weeks: dict[int, list[MemoryEvent]] = {}
        for ev in old_events:
            week_key = int(ev.timestamp // week_seconds)
            weeks.setdefault(week_key, []).append(ev)
        for week_key, week_events in weeks.items():
            if len(week_events) < 3:
                continue
            text = "\n".join(f"[{ev.category}]: {ev.content}" for ev in week_events)
            try:
                result = await self._compression_agent.run(
                    f"Compress these weekly memory events:\n\n{text}"
                )
                summary: _CompressionSummary | None = result.output
            except Exception as exc:
                logger.warning("Compression LLM call failed for week %d: %s", week_key, exc)
                continue
            if summary:
                try:
                    await self._event_log.insert(
                        category=summary.category,
                        content=f"[weekly summary] {summary.summary}",
                        source="consolidation",
                        importance=0.6,
                    )
                    for ev in week_events:
                        await self._event_log.mark_consolidated(ev.id)
                    logger.info("Compressed %d events for week %d", len(week_events), week_key)
                except Exception as exc:
                    logger.warning("Failed to store compression for week %d: %s", week_key, exc)

    async def _garbage_collect(self) -> None:
        """Delete old low-importance events that are no longer useful."""
        candidates = await self._event_log.get_gc_candidates(
            min_age_days=self._gc_days,
            max_importance=self._gc_min_importance,
        )
        for ev in candidates:
            try:
                await self._event_log.delete_event(ev.id)
                logger.debug("GC: deleted event %d (%s)", ev.id, ev.content[:50])
            except Exception as exc:
                logger.warning("GC failed for event %d: %s", ev.id, exc)
