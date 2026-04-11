from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass
class KoreMessage:
    """A single message in a conversation history."""

    role: Literal["user", "assistant"]
    content: str
    # Always UTC-aware — naive datetimes cause ordering bugs in the event log (Phase 3+)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ToolCall:
    """A tool call made by the agent, with its result once available."""

    tool_call_id: str          # used for correlation, not deduplication
    name: str
    args: dict[str, Any]
    result: Any | None = None


@dataclass
class AgentResponse:
    """Normalised response from any Kore agent."""

    content: str
    tool_calls: list[ToolCall]
    model_used: str
    output: Any | None = None  # populated with structured output when output_type is set
    reasoning_steps: list[str] = field(default_factory=list)  # text parts emitted between tool calls
