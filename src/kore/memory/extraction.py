from __future__ import annotations

import logging

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from kore.llm.types import KoreMessage
from kore.memory.event_log import EventLog

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """
You extract memorable facts and observations from conversations.
Given a conversation, identify facts worth remembering for future interactions.
Focus on: user preferences, personal facts, project details, corrections, decisions.
Ignore: pleasantries, filler, transient requests already fulfilled.
Return a JSON array of objects with keys: category, content, importance (0.0–1.0).
Categories: fact, preference, correction, project, conversation.
Return [] if nothing is worth remembering.
""".strip()


class _ExtractedEvent(BaseModel):
    category: str
    content: str
    importance: float = 0.5


class ExtractionAgent:
    """Extracts memory events from conversation turns after each session.

    Uses a cheap LLM (Haiku) to identify facts worth remembering and
    stores them in the event log. Called by the Orchestrator after each
    conversation turn.
    """

    def __init__(self, event_log: EventLog, model: str = "anthropic:claude-haiku-4-5-20251001") -> None:
        self._event_log = event_log
        _model = TestModel() if model == "test" else model
        self._agent: Agent = Agent(
            _model,
            system_prompt=_EXTRACTION_PROMPT,
            output_type=list[_ExtractedEvent],
        )

    async def extract_and_store(self, conversation: list[KoreMessage]) -> list[int]:
        """Extract facts from *conversation* and store to event log.

        Returns list of inserted event IDs. Returns [] for empty conversations.
        """
        if not conversation:
            return []

        # Format conversation for the LLM
        turns = "\n".join(f"{m.role.upper()}: {m.content}" for m in conversation)
        prompt = f"Extract memorable facts from this conversation:\n\n{turns}"

        try:
            result = await self._agent.run(prompt)
            extracted: list[_ExtractedEvent] = result.output or []
        except Exception as exc:
            logger.warning("Extraction failed: %s", exc)
            return []

        event_ids = []
        for item in extracted:
            try:
                eid = await self._event_log.insert(
                    category=item.category,
                    content=item.content,
                    source="extraction",
                    importance=max(0.0, min(1.0, item.importance)),
                )
                event_ids.append(eid)
            except Exception as exc:
                logger.warning("Failed to store extracted event: %s", exc)

        return event_ids
