from __future__ import annotations

from kore.agents.base import BaseAgent
from kore.config import KoreConfig
from kore.llm.provider import get_model

_COMPACTION_SYSTEM_PROMPT = (
    "You are a session summariser. When given an existing summary and additional "
    "session turns, produce a single concise summary incorporating both. "
    "Preserve key facts, decisions, context, and user preferences. Aim for 200-400 words."
)

_MERGE_TEMPLATE = """\
Existing summary (may be empty):
{summary}

Additional session turns:
{turns}

Produce an updated summary that incorporates both the existing summary and the new turns.\
"""


class Compactor:
    """Summarises old session turns into a compact summary using an LLM."""

    def __init__(self, model: object, model_string: str) -> None:
        self._agent = BaseAgent(model, model_string, _COMPACTION_SYSTEM_PROMPT)  # type: ignore[arg-type]

    @classmethod
    def from_config(cls, config: KoreConfig) -> Compactor:
        model = get_model(config.session.compaction_model, config)
        return cls(model, config.session.compaction_model)

    async def summarise(self, existing_summary: str | None, old_turns: list[dict]) -> str:
        """Merge existing_summary + old_turns into a new summary string."""
        turns_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in old_turns
        )
        prompt = _MERGE_TEMPLATE.format(
            summary=existing_summary or "(none)",
            turns=turns_text,
        )
        result = await self._agent.run(prompt)
        return result.content
