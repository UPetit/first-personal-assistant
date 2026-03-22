# Session Debugger — Design Spec

**Date:** 2026-03-21
**Status:** Approved

## Goal

Add a Sessions page to the Kore UI that lists past sessions and shows a live execution trace for active ones. The trace shows the planner decision, each executor, and every tool call with its arguments and result — inline between the user and assistant messages. Designed as a developer debugging tool, gated behind a config flag.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Live streaming | WebSocket `/ws/sessions` with in-process event bus | Clean separation from log stream; structured events |
| Config gate | `debug.session_tracing: bool = false` | Zero overhead when disabled; easy to toggle |
| UI layout | Sidebar session list + inline unified timeline | Trace appears between messages; tool calls collapsible |
| Tool results | Included, capped at 500 chars | Enough for debugging without flooding the UI |
| Late-join replay | Ring buffer of last 200 events | Late-connecting clients get recent context |
| Session history | Read from `workspace/sessions/*.json` | Already persisted by `SessionBuffer` |

---

## 1. Config

New `DebugConfig` model added to `src/kore/config.py`:

```python
class DebugConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_tracing: bool = False
```

Added to `KoreConfig`:
```python
debug: DebugConfig = DebugConfig()
```

`config.json` to enable:
```json
"debug": {
  "session_tracing": true
}
```

When `session_tracing` is `false`, the `EventBus` is never instantiated, the orchestrator receives `event_bus=None`, and `/ws/sessions` returns HTTP 503.

---

## 2. Event Bus

**File:** `src/kore/gateway/event_bus.py`

```python
class EventBus:
    def __init__(self, maxsize: int = 200) -> None: ...
    async def emit(self, event: dict) -> None: ...
    def subscribe(self) -> asyncio.Queue: ...
    def unsubscribe(self, queue: asyncio.Queue) -> None: ...
    def recent(self, n: int) -> list[dict]: ...
```

- `emit()` puts the event to all subscriber queues and appends to an internal ring buffer (capped at `maxsize`).
- `subscribe()` returns a new `asyncio.Queue`; `unsubscribe()` removes it.
- `recent(n)` returns the last `n` events from the ring buffer for late-join replay.
- All events are plain dicts — no Pydantic model, keeping the bus dependency-free.

---

## 3. Event Schema

Every event is a JSON object with these common fields:

```json
{
  "type": "<event_type>",
  "session_id": "<str>",
  "ts": "<ISO 8601 UTC>"
}
```

Plus type-specific payload:

| `type` | Additional fields |
|--------|------------------|
| `session_start` | `message: str` |
| `plan_result` | `executor: str`, `instruction: str`, `reasoning: str` |
| `executor_start` | `executor_name: str`, `model: str` |
| `tool_call` | `tool_name: str`, `args: dict` |
| `tool_result` | `tool_name: str`, `result: str` (capped 500 chars) |
| `executor_done` | `content_preview: str` (first 200 chars) |
| `session_done` | `response: str` |
| `session_error` | `error: str` |

---

## 4. Orchestrator Instrumentation

**File:** `src/kore/agents/orchestrator.py`

`Orchestrator.__init__` gains an optional `event_bus` parameter:

```python
def __init__(self, config, ..., event_bus=None) -> None:
    self._bus = event_bus
```

Helper:
```python
async def _emit(self, event: dict) -> None:
    if self._bus is not None:
        await self._bus.emit(event)
```

Emission points in `run()`:

1. **Entry** → `session_start`
2. **After planner returns** → `plan_result` (one per step)
3. **Before each executor runs** → `executor_start`
4. **After each executor** → `executor_done`
5. **Final return** → `session_done`
6. **On exception** → `session_error`

Tool calls (`tool_call`, `tool_result`) are extracted from `last_response.tool_calls` after each executor run and emitted in order.

---

## 5. WebSocket Endpoint

**File:** `src/kore/gateway/routes_ws.py` (extend existing)

```
WS /ws/sessions
```

- If `app.state.event_bus is None` → close immediately with code 1013 (try again later).
- On connect: replay `event_bus.recent(200)` to the client.
- Stream live events until disconnect.
- Cleanup: `event_bus.unsubscribe(queue)` in `finally`.

---

## 6. REST Endpoints

**File:** `src/kore/gateway/routes_api.py` (extend existing)

### `GET /api/sessions`

Reads all `*.json` files from `workspace/sessions/`, returns:

```json
[
  {
    "session_id": "telegram_1582227539",
    "created_at": "2026-03-21T18:00:00+00:00",
    "turn_count": 3,
    "last_message": "Give me today's recipes"
  }
]
```

Sorted by `created_at` descending (newest first).

### `GET /api/sessions/{session_id}`

Returns full session content from the JSON file:

```json
{
  "session_id": "telegram_1582227539",
  "created_at": "2026-03-21T18:00:00+00:00",
  "summary": null,
  "turns": [
    { "role": "user", "content": "...", "timestamp": "..." },
    { "role": "assistant", "content": "...", "timestamp": "..." }
  ]
}
```

Returns 404 if session file not found.

---

## 7. UI — Sessions Page

**File:** `ui/src/pages/Sessions.jsx`

### Layout

Two-panel layout:

- **Left sidebar (200px):** session list, sorted newest-first. Each entry shows: `session_id`, relative time, turn count, first line of last user message. Active session highlighted with left border accent.
- **Right panel:** session detail — unified vertical timeline.

### Timeline Structure

For each turn in the session:

```
[User message bubble — right-aligned]
[Execution trace block — collapsible]
  ├── Planner row: executor name + reasoning (one line)
  ├── tool_call row: tool name + args JSON (expandable)
  │   └── tool_result: result string (expandable)
  └── (more tool calls...)
[Assistant message bubble — left-aligned]
```

The trace block is **collapsed by default** (shows planner + tool names only). Clicking a tool call expands args and result inline.

### Live Mode

When `session_tracing` is enabled in config:

- Sessions page connects to `/ws/sessions` on mount.
- Incoming events for the selected session are rendered live — tool calls appear as they happen, before the assistant message arrives.
- A pulsing indicator shows the session is active.
- Sessions with no matching WebSocket events (tracing disabled or historical) show only the persisted chat turns from `GET /api/sessions/{id}`.

### Wiring

- `ui/src/App.jsx`: add `/sessions` route and nav link.
- Nav label: **Sessions** (between Logs and Memory, or after Agents).

---

## 8. server.py Wiring

**File:** `src/kore/gateway/server.py`

```python
if config.debug.session_tracing:
    from kore.gateway.event_bus import EventBus
    app.state.event_bus = EventBus()
else:
    app.state.event_bus = None
```

**File:** `src/kore/main.py`

```python
orchestrator = Orchestrator(
    config,
    ...,
    event_bus=app.state.event_bus,  # None if tracing disabled
)
```

---

## 9. Testing

### `tests/test_event_bus.py`

- `emit()` delivers to all subscribers
- `recent()` returns last N events from ring buffer
- `unsubscribe()` stops delivery to that queue
- Ring buffer caps at maxsize (oldest dropped)

### `tests/test_session_debugger.py`

- Orchestrator with `event_bus` emits `session_start`, `plan_result`, `tool_call`, `tool_result`, `session_done` in correct order
- Orchestrator without `event_bus` emits nothing (no AttributeError)
- `GET /api/sessions` lists sessions sorted newest-first
- `GET /api/sessions/{id}` returns full turn data
- `GET /api/sessions/nonexistent` returns 404
- `/ws/sessions` replays recent events to late-joining client
- `/ws/sessions` returns 503 when `event_bus` is None

### UI

No automated tests for React components — manual verification against the mockup.
