from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_core_memory_update_tool(memory_deps):
    from kore.tools.memory_tools import core_memory_update
    result = await core_memory_update(memory_deps, "user.name", "Alice")
    assert "updated" in result.lower()
    assert memory_deps.deps.core_memory.get()["user"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_core_memory_update_tool_token_cap(memory_deps):
    from kore.tools.memory_tools import core_memory_update
    from kore.memory.core_memory import CoreMemory
    # Override with tiny cap
    memory_deps.deps.core_memory = CoreMemory(
        memory_deps.deps.core_memory._path, max_tokens=5
    )
    result = await core_memory_update(memory_deps, "key", "x" * 10000)
    assert "error" in result.lower() or "cap" in result.lower()


@pytest.mark.asyncio
async def test_core_memory_delete_tool(memory_deps):
    from kore.tools.memory_tools import core_memory_delete, core_memory_update
    await core_memory_update(memory_deps, "user.name", "Bob")
    result = await core_memory_delete(memory_deps, "user.name")
    assert "deleted" in result.lower() or "removed" in result.lower()
    assert "name" not in memory_deps.deps.core_memory.get().get("user", {})


@pytest.mark.asyncio
async def test_memory_store_tool(memory_deps):
    from kore.tools.memory_tools import memory_store
    result = await memory_store(memory_deps, "fact", "Alice likes cats", "user", 0.8)
    assert "stored" in result.lower() or "saved" in result.lower()


@pytest.mark.asyncio
async def test_memory_search_tool_finds_result(memory_deps):
    from kore.tools.memory_tools import memory_search, memory_store
    await memory_store(memory_deps, "fact", "Python is a programming language", "user", 0.9)
    result = await memory_search(memory_deps, "Python programming", max_results=5)
    assert "Python" in result


@pytest.mark.asyncio
async def test_memory_search_tool_empty_result(memory_deps):
    from kore.tools.memory_tools import memory_search
    result = await memory_search(memory_deps, "quantum physics unicorn", max_results=5)
    assert isinstance(result, str)


def test_memory_tools_registered():
    """All memory tools must be registered in the tool registry."""
    import kore.tools.memory_tools  # noqa: F401 — triggers registration
    from kore.tools.registry import get_tools
    tools = get_tools(["core_memory_update", "core_memory_delete", "memory_search", "memory_store"])
    assert len(tools) == 4
