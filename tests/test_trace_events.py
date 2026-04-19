from __future__ import annotations

import uuid

from kore.gateway.trace_events import (
    EventKind,
    EventType,
    new_span_id,
    span_event,
)


def test_new_span_id_is_uuid4():
    sid = new_span_id()
    uuid.UUID(sid, version=4)  # does not raise


def test_span_event_root_session():
    ev = span_event(
        type_=EventType.SESSION_START,
        kind=EventKind.SESSION,
        session_id="s1",
        parent_span_id=None,
        extra={"message": "hi"},
    )
    assert ev["type"] == "session_start"
    assert ev["kind"] == "session"
    assert ev["parent_span_id"] is None
    assert ev["message"] == "hi"
    uuid.UUID(ev["span_id"], version=4)


def test_span_event_child_carries_parent():
    ev = span_event(
        type_=EventType.TOOL_CALL,
        kind=EventKind.TOOL,
        session_id="s1",
        parent_span_id="PARENT-SPAN-ID",
        extra={"tool_name": "memory_search", "args": {"q": "x"}},
    )
    assert ev["parent_span_id"] == "PARENT-SPAN-ID"
    assert ev["kind"] == "tool"
    assert ev["tool_name"] == "memory_search"
