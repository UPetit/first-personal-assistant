from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
from kore.tools.registry import register


async def core_memory_update(ctx: RunContext[KoreDeps], path: str, value: Any) -> str:
    """Update a value in core memory at the given dot-notation path.

    Example: ``core_memory_update(ctx, "user.name", "Alice")``
    Creates intermediate dicts as needed. Raises if the 4,000-token cap
    would be exceeded — the store is left unchanged in that case.
    """
    core_mem = ctx.deps.core_memory
    try:
        core_mem.update(path, value)
        return f"Core memory updated: {path!r} = {value!r}"
    except Exception as exc:
        return f"[Error: {exc}]"


async def core_memory_delete(ctx: RunContext[KoreDeps], path: str) -> str:
    """Delete a key from core memory at the given dot-notation path.

    No-op if the path does not exist.
    """
    core_mem = ctx.deps.core_memory
    try:
        core_mem.delete(path)
        return f"Core memory key deleted: {path!r}"
    except Exception as exc:
        return f"[Error: {exc}]"


async def memory_search(ctx: RunContext[KoreDeps], query: str, max_results: int = 10) -> str:
    """Search the event log for memories relevant to *query*.

    Returns a formatted string of matching events, ranked by relevance and recency.
    Returns a message indicating no results if nothing matches.
    """
    retriever = ctx.deps.retriever
    try:
        results = await retriever.search(query)
        if not results:
            return "(no relevant memories found)"
        lines = []
        for r in results[: max_results]:
            ev = r.event
            lines.append(
                f"[{ev.category}] ({ev.source or 'unknown'}, score={r.score:.2f}): {ev.content}"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"[Error searching memories: {exc}]"


async def memory_store(
    ctx: RunContext[KoreDeps],
    category: str,
    content: str,
    source: str = "assistant",
    importance: float = 0.5,
) -> str:
    """Explicitly store a fact or observation to the event log.

    Use this when you learn something worth remembering for future conversations.
    ``category`` should be one of: ``fact``, ``preference``, ``correction``,
    ``project``, ``conversation``.
    ``importance`` is 0.0–1.0 (default 0.5).
    """
    event_log = ctx.deps.event_log
    try:
        event_id = await event_log.insert(
            category=category,
            content=content,
            source=source,
            importance=max(0.0, min(1.0, importance)),
        )
        return f"Memory stored (id={event_id}): {content[:80]!r}"
    except Exception as exc:
        return f"[Error storing memory: {exc}]"


register("core_memory_update", core_memory_update)
register("core_memory_delete", core_memory_delete)
register("memory_search", memory_search)
register("memory_store", memory_store)
