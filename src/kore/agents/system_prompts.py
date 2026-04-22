from __future__ import annotations

from datetime import datetime, timezone


def current_time_fragment() -> str:
    """Return a system-prompt fragment stating today's UTC date and time.

    Registered on each agent via ``@agent.system_prompt`` so pydantic-ai
    recomputes it on every ``agent.run()`` — avoids stale dates on long-lived
    agent instances and removes the need for the subagent to call
    ``get_current_time`` before doing time-sensitive work (e.g. web search).
    """
    now = datetime.now(timezone.utc)
    return (
        f"Today is {now.strftime('%Y-%m-%d')} (UTC). "
        f"Current time: {now.strftime('%H:%M')} UTC."
    )
