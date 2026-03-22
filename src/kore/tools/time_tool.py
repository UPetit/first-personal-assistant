from __future__ import annotations

from datetime import datetime, timezone

from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
from kore.tools.registry import register


async def get_current_time(ctx: RunContext[KoreDeps]) -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


register("get_current_time", get_current_time)
