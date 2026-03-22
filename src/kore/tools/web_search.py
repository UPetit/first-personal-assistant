from __future__ import annotations

import asyncio
import httpx
from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
from kore.tools.registry import register

_BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Brave free tier: ~1 req/sec. Serialize all calls with a lock + post-request delay
# to prevent 429s when the LLM issues multiple web_search tool calls in one response.
_search_lock: asyncio.Lock | None = None


def _get_search_lock() -> asyncio.Lock:
    global _search_lock
    if _search_lock is None:
        _search_lock = asyncio.Lock()
    return _search_lock


async def web_search(
    ctx: RunContext[KoreDeps],
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """Search the web using Brave Web Search API. Returns title, url, and description per result.

    Each result contains {title, url, description} — search snippets ready to use.

    On any error (HTTP, timeout, missing key) returns [{"error": "<message>"}] rather
    than raising — the agent decides how to handle search failures.
    """
    tool_cfg = ctx.deps.config.tools.get("web_search")
    if tool_cfg is None or tool_cfg.api_key is None:
        return [{"error": "Brave Search API key not configured"}]

    api_key = tool_cfg.api_key.get_secret_value()

    async with _get_search_lock():
        result = await _do_search(api_key, query, max_results)
        await asyncio.sleep(1.1)  # stay within Brave free-tier rate limit
    return result


async def _do_search(api_key: str, query: str, max_results: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                _BRAVE_WEB_SEARCH_URL,
                params={"q": query, "count": max_results, "extra_snippets": True},
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException as exc:
        return [{"error": f"Search timed out: {exc}"}]
    except Exception as exc:
        return [{"error": f"Search failed: {exc}"}]

    results = []
    for entry in data.get("web", {}).get("results", []):
        results.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("url", ""),
                "description": entry.get("description", ""),
                "extra_snippets": entry.get("extra_snippets", []),
            }
        )
    return results


register("web_search", web_search)
