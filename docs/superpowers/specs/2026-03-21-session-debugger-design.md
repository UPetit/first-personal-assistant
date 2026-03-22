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
| Session history | Read from `~/.kore/workspace/sessions/*.json` | Already persisted by `SessionBuffer` |
| Tool call emission | Batch after each executor completes | pydantic-ai exposes tool calls post-run only; batch is correct granularity |
| Disabled endpoint | HTTP 503 before WebSocket handshake | Cleaner than closing after accept; standard REST semantics |

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

When `session_tracing` is `false`, the `EventBus` is never instantiated, the orchestrator receives `event_bus=None`, and `/ws/sessions` returns HTTP 503 before the WebSocket handshake.

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

Per-step events (`plan_result`, `executor_start`, `tool_call`, `tool_result`, `executor_done`) also include `"step_index": <int>`, a zero-based counter that increments with each planner step (each `plan_result` → executor cycle). Session-level events (`session_start`, `session_done`, `session_error`) omit `step_index`.

Plus type-specific payload:

| `type` | Additional fields (beyond common fields) |
|--------|------------------------------------------|
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

`Orchestrator.__init__` gains an optional `event_bus` parameter added to the existing signature:

```python
def __init__(
    self,
    config: KoreConfig,
    core_memory=None,
    event_log=None,
    retriever=None,
    extraction_agent=None,
    event_bus: EventBus | None = None,
) -> None:
    ...
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
2. **After planner returns** → `plan_result` (one per step, with `step_index`)
3. **Before each executor runs** → `executor_start` (with `step_index`)
4. **After each executor** → emit `tool_call`/`tool_result` pairs in order (extracted from `last_response.tool_calls`), then `executor_done` — all with same `step_index`
5. **Final return** → `session_done`
6. **On exception** → `session_error`

**Tool call emission strategy:** pydantic-ai's `capture_run_messages()` is only available after the executor run completes. Tool calls are therefore emitted as a batch after each executor finishes, not in real-time during execution. This is the correct and expected behavior.

---

## 5. WebSocket Endpoint

**File:** `src/kore/gateway/routes_ws.py` (extend existing)

```
WS /ws/sessions
```

- If `app.state.event_bus is None` → return HTTP 503 **before** calling `websocket.accept()`.
- On connect: replay `event_bus.recent(200)` to the client as JSON text frames.
- Stream live events as JSON text frames (`websocket.send_text(json.dumps(event))`) until disconnect.
- Cleanup: `event_bus.unsubscribe(queue)` in `finally`.

Returning 503 before the handshake allows the client to handle the error as a normal HTTP response rather than a mid-stream WebSocket close.

---

## 6. REST Endpoints

**File:** `src/kore/gateway/routes_api.py` (extend existing)

These endpoints inherit the existing basic auth middleware applied to all `/api/*` routes.

### `GET /api/sessions`

Reads all `*.json` files from `~/.kore/workspace/sessions/` (use the module-level `_sessions_dir()` from `kore.session.buffer` to resolve this path — it is a standalone function, not a class method). If the directory does not exist, returns `[]`.

Returns:

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

- `turn_count`: `len(session["turns"]) // 2`. After compaction, `SessionBuffer` retains only the most recent `keep_recent_turns` turns in the `"turns"` list; `turn_count` reflects in-file turns only (no adjustment for the compacted summary).
- `last_message`: the `content` of the last turn with `role == "user"`, first 100 characters.
- Sorted by `created_at` descending (newest first).

### `GET /api/sessions/{session_id}`

Returns full session content from the JSON file at `~/.kore/workspace/sessions/{session_id}.json`:

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

- **Left sidebar (200px):** session list, sorted newest-first. Each entry shows: `session_id`, relative time, turn count, first 100 characters of last user message. Active session highlighted with left border accent.
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

### WebSocket Degradation

If the `/ws/sessions` connection fails or returns 503:

- The page silently falls back to REST-only mode (no pulsing indicator, no live events).
- A subtle status note reads "Live trace unavailable — enable `debug.session_tracing` in config."
- Historical session data from `GET /api/sessions/{id}` still loads and displays normally.

### Wiring

- `ui/src/App.jsx`: add `/sessions` route and nav link.
- Nav label: **Sessions** (between Logs and Memory, or after Agents).

---

## 8. Wiring

**File:** `src/kore/gateway/server.py`

`create_app` gains a new `event_bus` keyword argument alongside the existing ones:

```python
def create_app(
    config: KoreConfig,
    *,
    queue: MessageQueue | None = None,
    scheduler: KoreCronScheduler | None = None,
    core_memory: CoreMemory | None = None,
    orchestrator: Orchestrator | None = None,
    telegram_channel: TelegramChannel | None = None,
    event_bus: EventBus | None = None,   # new
) -> FastAPI:
    ...
    app.state.event_bus = event_bus
```

**File:** `src/kore/main.py`

The `EventBus` is instantiated in `main.py` and passed to both `create_app()` and `Orchestrator`:

```python
from kore.gateway.event_bus import EventBus

event_bus = EventBus() if config.debug.session_tracing else None

raw_orchestrator = Orchestrator(config, event_bus=event_bus)

app = create_app(
    config,
    queue=queue,
    scheduler=scheduler,
    orchestrator=raw_orchestrator,
    telegram_channel=telegram_channel,
    event_bus=event_bus,
)
```

Both `create_app()` and `Orchestrator` receive the same instance, ensuring the WebSocket handler and orchestrator share one ring buffer.

---

## 9. Testing

### `tests/test_event_bus.py`

- `emit()` delivers to a single subscriber
- `emit()` fans out to multiple subscribers (all queues receive the event)
- `recent()` returns last N events from ring buffer
- `unsubscribe()` stops delivery to that queue
- Ring buffer caps at maxsize (oldest dropped)

### `tests/test_session_debugger.py`

- Orchestrator with `event_bus` emits events in correct order: `session_start`, `plan_result`, `executor_start`, `tool_call`, `tool_result`, `executor_done`, `session_done` — with correct `step_index` values
- Orchestrator without `event_bus` emits nothing (no AttributeError)
- `GET /api/sessions` lists sessions sorted newest-first
- `GET /api/sessions` returns `[]` when sessions directory does not exist
- `GET /api/sessions/{id}` returns full turn data
- `GET /api/sessions/nonexistent` returns 404
- `/ws/sessions` replays recent events as JSON text frames to late-joining client
- `/ws/sessions` returns HTTP 503 before handshake when `event_bus` is None
- `create_app(config, event_bus=None)` sets `app.state.event_bus` to `None`

### UI

No automated tests for React components — manual verification against the mockup.
