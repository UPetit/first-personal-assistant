from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kore.config import KoreConfig


@dataclass
class KoreDeps:
    """Dependency container injected into every agent run via RunContext.deps.

    All fields except *config* are optional — agents that don't use memory or
    retrieval receive None and their tools handle the absence gracefully.

    Usage in tools::

        async def my_tool(ctx: RunContext[KoreDeps], ...) -> str:
            cfg = ctx.deps.config
            mem = ctx.deps.core_memory  # may be None
    """

    config: KoreConfig
    core_memory: Any = field(default=None)   # CoreMemory | None
    event_log: Any = field(default=None)     # EventLog | None
    retriever: Any = field(default=None)     # Retriever | None
    skill_registry: Any = field(default=None)  # SkillRegistry | None
