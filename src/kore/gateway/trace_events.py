from __future__ import annotations

import uuid
from enum import Enum
from typing import Any


class EventKind(str, Enum):
    SESSION = "session"
    PRIMARY = "primary"
    TOOL = "tool"
    SUBAGENT = "subagent"


class EventType(str, Enum):
    SESSION_START = "session_start"
    PRIMARY_START = "primary_start"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_DONE = "subagent_done"
    PRIMARY_DONE = "primary_done"
    SESSION_DONE = "session_done"
    SESSION_ERROR = "session_error"


def new_span_id() -> str:
    """Return a fresh span identifier (UUID4 hex string)."""
    return str(uuid.uuid4())


def span_event(
    *,
    type_: EventType,
    kind: EventKind,
    session_id: str,
    parent_span_id: str | None,
    span_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a trace event dict with span-tracking fields.

    The returned dict can be passed directly to TraceStore.add(). It carries:

    - span_id: UUID4 for this event
    - parent_span_id: parent's span_id (None for session_start only)
    - kind: one of session|primary|tool|subagent
    - type: the EventType string value
    - session_id: conversation/session identifier
    - plus any keys in *extra*
    """
    event: dict[str, Any] = {
        "type": type_.value,
        "kind": kind.value,
        "session_id": session_id,
        "span_id": span_id or new_span_id(),
        "parent_span_id": parent_span_id,
    }
    if extra:
        event.update(extra)
    return event
