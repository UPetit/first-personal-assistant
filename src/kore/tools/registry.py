from __future__ import annotations

from collections.abc import Callable

# Global tool registry: name → async callable
_TOOLS: dict[str, Callable] = {}


def register(name: str, fn: Callable) -> None:
    """Register a tool callable by name. Called at module import by each tool file."""
    _TOOLS[name] = fn


def get(name: str) -> Callable:
    """Return the callable for the given name. Raises KeyError if not registered."""
    if name not in _TOOLS:
        raise KeyError(
            f"Tool {name!r} is not registered. Available: {sorted(_TOOLS)}"
        )
    return _TOOLS[name]


def get_tools(names: list[str]) -> list[Callable]:
    """Return callables for all names in order. Raises KeyError on the first unknown name."""
    return [get(name) for name in names]


def all_tools() -> dict[str, Callable]:
    """Return a snapshot of the full registry (for introspection/testing)."""
    return dict(_TOOLS)
