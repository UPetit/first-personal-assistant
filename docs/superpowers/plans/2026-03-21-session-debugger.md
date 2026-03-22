# Session Debugger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Sessions page to the Kore UI that shows live execution traces (planner decisions, tool calls, results) streamed via WebSocket, gated behind a config flag.

**Architecture:** An in-process `EventBus` (ring buffer + subscriber queues) lives in `src/kore/gateway/event_bus.py`. The `Orchestrator` accepts an optional `event_bus` and emits structured events at each pipeline milestone. A new `/ws/sessions` WebSocket endpoint fans those events to connected UI clients; a pair of REST endpoints (`GET /api/sessions`, `GET /api/sessions/{id}`) serve historical session data already persisted by `SessionBuffer`. The React `Sessions.jsx` page shows a two-panel layout (session list + timeline), connects to the WebSocket for live events, and gracefully degrades to REST-only if the socket is unavailable.

**Tech Stack:** Python asyncio, FastAPI WebSocket, React + hooks, existing `SessionBuffer` JSON files, `AgentResponse.tool_calls` (pydantic-ai post-run batch).

---

## File Map

| Status | Path | Role |
|--------|------|------|
| **Create** | `src/kore/gateway/event_bus.py` | EventBus: ring buffer, subscriber queues, emit/subscribe/unsubscribe/recent |
| **Modify** | `src/kore/config.py` | Add `DebugConfig`, add `debug` field to `KoreConfig` |
| **Modify** | `src/kore/agents/orchestrator.py` | Add `event_bus` param, `_emit()` helper, emission points in `run()` |
| **Modify** | `src/kore/gateway/routes_ws.py` | Add `/ws/sessions` endpoint |
| **Modify** | `src/kore/gateway/routes_api.py` | Add `GET /api/sessions` and `GET /api/sessions/{id}` |
| **Modify** | `src/kore/gateway/server.py` | Add `event_bus` param to `create_app`, store in `app.state` |
| **Modify** | `src/kore/main.py` | Instantiate `EventBus` when `debug.session_tracing` is true, pass through |
| **Create** | `ui/src/pages/Sessions.jsx` | Two-panel Sessions page with live WebSocket + REST fallback |
| **Modify** | `ui/src/App.jsx` | Add `/sessions` route and nav entry |
| **Create** | `tests/test_event_bus.py` | EventBus unit tests |
| **Create** | `tests/test_session_debugger.py` | Orchestrator events, REST endpoints, WebSocket endpoint, wiring |

---

## Task 1: Config — DebugConfig

**Files:**
- Modify: `src/kore/config.py`
- Test: `tests/test_config.py` (append to existing file)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_debug_config_defaults_session_tracing_false():
    from kore.config import DebugConfig
    cfg = DebugConfig()
    assert cfg.session_tracing is False


def test_kore_config_has_debug_field(sample_config):
    from kore.config import DebugConfig
    assert hasattr(sample_config, "debug")
    assert isinstance(sample_config.debug, DebugConfig)
    assert sample_config.debug.session_tracing is False


def test_debug_session_tracing_can_be_enabled():
    from kore.config import DebugConfig
    cfg = DebugConfig(session_tracing=True)
    assert cfg.session_tracing is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python -m pytest tests/test_config.py::test_debug_config_defaults_session_tracing_false -v
```
Expected: `FAILED` — `ImportError: cannot import name 'DebugConfig'`

- [ ] **Step 3: Implement DebugConfig in config.py**

After the `UIConfig` class (around line 32), add:

```python
class DebugConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_tracing: bool = False
```

In `KoreConfig` (around line 172), add the field after `scheduler`:

```python
debug: DebugConfig = DebugConfig()
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /root/kore-ai && python -m pytest tests/test_config.py -v -k "debug"
```
Expected: 3 tests `PASSED`

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
cd /root/kore-ai && python -m pytest tests/test_config.py -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd /root/kore-ai && git add src/kore/config.py tests/test_config.py
git commit -m "feat: add DebugConfig with session_tracing flag"
```

---

## Task 2: EventBus

**Files:**
- Create: `src/kore/gateway/event_bus.py`
- Create: `tests/test_event_bus.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event_bus.py`:

```python
from __future__ import annotations

import asyncio
import pytest


@pytest.mark.asyncio
async def test_emit_delivers_to_single_subscriber():
    from kore.gateway.event_bus import EventBus
    bus = EventBus()
    q = bus.subscribe()
    event = {"type": "session_start", "session_id": "s1", "ts": "2026-01-01T00:00:00Z"}
    await bus.emit(event)
    received = q.get_nowait()
    assert received == event


@pytest.mark.asyncio
async def test_emit_fans_out_to_multiple_subscribers():
    from kore.gateway.event_bus import EventBus
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    event = {"type": "session_start", "session_id": "s1", "ts": "t"}
    await bus.emit(event)
    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    from kore.gateway.event_bus import EventBus
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    await bus.emit({"type": "x", "session_id": "s1", "ts": "t"})
    assert q.empty()


@pytest.mark.asyncio
async def test_recent_returns_last_n_events():
    from kore.gateway.event_bus import EventBus
    bus = EventBus()
    for i in range(5):
        await bus.emit({"type": "x", "session_id": "s1", "ts": str(i), "i": i})
    result = bus.recent(3)
    assert len(result) == 3
    assert result[0]["i"] == 2  # oldest of the last 3
    assert result[2]["i"] == 4  # newest


@pytest.mark.asyncio
async def test_ring_buffer_caps_at_maxsize():
    from kore.gateway.event_bus import EventBus
    bus = EventBus(maxsize=3)
    for i in range(5):
        await bus.emit({"type": "x", "session_id": "s1", "ts": str(i), "i": i})
    result = bus.recent(10)
    assert len(result) == 3
    assert result[0]["i"] == 2  # oldest kept
    assert result[2]["i"] == 4  # newest
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python -m pytest tests/test_event_bus.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'kore.gateway.event_bus'`

- [ ] **Step 3: Implement EventBus**

Create `src/kore/gateway/event_bus.py`:

```python
from __future__ import annotations

import asyncio
from collections import deque


class EventBus:
    """In-process pub/sub bus for live session trace events.

    - emit() puts the event to all subscriber queues and appends to a ring buffer.
    - subscribe() returns a new asyncio.Queue; unsubscribe() removes it.
    - recent(n) returns the last n events from the ring buffer for late-join replay.
    - Events are plain dicts — no Pydantic dependency.
    """

    def __init__(self, maxsize: int = 200) -> None:
        self._buffer: deque[dict] = deque(maxlen=maxsize)
        self._subscribers: list[asyncio.Queue[dict]] = []

    async def emit(self, event: dict) -> None:
        """Broadcast event to all subscribers and append to ring buffer."""
        self._buffer.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer — drop rather than block

    def subscribe(self) -> asyncio.Queue[dict]:
        """Register a new subscriber queue and return it."""
        q: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        """Remove a subscriber queue; safe to call if already removed."""
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def recent(self, n: int) -> list[dict]:
        """Return the last n events from the ring buffer."""
        entries = list(self._buffer)
        return entries[-n:] if n < len(entries) else entries
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /root/kore-ai && python -m pytest tests/test_event_bus.py -v
```
Expected: all 5 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
cd /root/kore-ai && git add src/kore/gateway/event_bus.py tests/test_event_bus.py
git commit -m "feat: add EventBus for live session trace streaming"
```

---

## Task 3: Orchestrator Instrumentation

**Files:**
- Modify: `src/kore/agents/orchestrator.py`
- Create: `tests/test_session_debugger.py` (orchestrator tests only for now)

The `Orchestrator.run()` loop iterates `plan.steps`. For each step at index `i`, emit:
1. `plan_result` (with `step_index=i`, `executor`, `instruction`, `reasoning` from the top-level plan)
2. `executor_start` (with `step_index=i`, `executor_name`, `model`)
3. After executor finishes: for each `tool_call` in `last_response.tool_calls`, emit `tool_call` then `tool_result` (both with `step_index=i`)
4. `executor_done` (with `step_index=i`, `content_preview`)

Top-level session events: `session_start` at entry, `session_done` on success, `session_error` on exception.

The `ToolCall` dataclass (in `src/kore/llm/types.py`) has fields: `tool_call_id`, `name`, `args`, `result`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_debugger.py`:

```python
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_config():
    from pydantic import SecretStr
    from kore.config import (
        AgentsConfig, ExecutorConfig, KoreConfig, LLMConfig, LLMProviderConfig,
    )
    return KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={"anthropic": LLMProviderConfig(api_key=SecretStr("k"))}),
        agents=AgentsConfig(
            planner=ExecutorConfig(
                model="anthropic:claude-haiku-4-5-20251001",
                prompt_file="planner.md",
                tools=[],
            ),
            executors={
                "general": ExecutorConfig(
                    model="anthropic:claude-haiku-4-5-20251001",
                    prompt_file="general.md",
                    tools=[],
                )
            },
        ),
    )


def _make_plan_result(executor: str = "general", instruction: str = "Do something"):
    from kore.agents.planner import PlanResult, PlanStep
    return PlanResult(
        intent="test intent",
        reasoning="test reasoning",
        steps=[PlanStep(executor=executor, instruction=instruction)],
    )


def _make_agent_response(content: str = "done", tool_calls=None):
    from kore.llm.types import AgentResponse
    return AgentResponse(
        content=content,
        tool_calls=tool_calls or [],
        model_used="anthropic:claude-haiku-4-5-20251001",
    )


@pytest.mark.asyncio
async def test_orchestrator_emits_events_in_correct_order(kore_home):
    """With event_bus wired in, run() emits session_start → plan_result →
    executor_start → executor_done → session_done in the right order."""
    from kore.gateway.event_bus import EventBus
    from kore.agents.orchestrator import Orchestrator

    config = _make_config()
    bus = EventBus()
    q = bus.subscribe()

    plan_response = MagicMock()
    plan_response.output = _make_plan_result()
    exec_response = _make_agent_response("hello")

    orch = Orchestrator(config, event_bus=bus)
    with (
        patch.object(orch._planner, "run", new=AsyncMock(return_value=plan_response)),
        patch.object(orch, "_get_executor") as mock_get_exec,
    ):
        mock_exec = MagicMock()
        mock_exec.run = AsyncMock(return_value=exec_response)
        mock_get_exec.return_value = mock_exec

        await orch.run("hello", "test_session")

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    types = [e["type"] for e in events]
    assert types == [
        "session_start",
        "plan_result",
        "executor_start",
        "executor_done",
        "session_done",
    ]
    assert events[0]["message"] == "hello"
    assert events[1]["step_index"] == 0
    assert events[1]["executor"] == "general"
    assert events[1]["reasoning"] == "test reasoning"
    assert events[2]["step_index"] == 0
    assert events[2]["executor_name"] == "general"
    assert events[3]["step_index"] == 0
    assert events[4]["response"] == "hello"


@pytest.mark.asyncio
async def test_orchestrator_emits_tool_call_and_result_events(kore_home):
    """When executor has tool_calls, tool_call and tool_result events are emitted."""
    from kore.gateway.event_bus import EventBus
    from kore.agents.orchestrator import Orchestrator
    from kore.llm.types import ToolCall

    config = _make_config()
    bus = EventBus()
    q = bus.subscribe()

    tc = ToolCall(tool_call_id="tc1", name="web_search", args={"query": "test"}, result="results")
    plan_response = MagicMock()
    plan_response.output = _make_plan_result()
    exec_response = _make_agent_response("done", tool_calls=[tc])

    orch = Orchestrator(config, event_bus=bus)
    with (
        patch.object(orch._planner, "run", new=AsyncMock(return_value=plan_response)),
        patch.object(orch, "_get_executor") as mock_get_exec,
    ):
        mock_exec = MagicMock()
        mock_exec.run = AsyncMock(return_value=exec_response)
        mock_get_exec.return_value = mock_exec

        await orch.run("search this", "test_session")

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types

    tc_event = next(e for e in events if e["type"] == "tool_call")
    tr_event = next(e for e in events if e["type"] == "tool_result")
    assert tc_event["tool_name"] == "web_search"
    assert tc_event["args"] == {"query": "test"}
    assert tc_event["step_index"] == 0
    assert tr_event["tool_name"] == "web_search"
    assert tr_event["result"] == "results"
    assert tr_event["step_index"] == 0


@pytest.mark.asyncio
async def test_orchestrator_without_event_bus_emits_nothing(kore_home):
    """Orchestrator with event_bus=None must not raise AttributeError."""
    from kore.agents.orchestrator import Orchestrator

    config = _make_config()
    plan_response = MagicMock()
    plan_response.output = _make_plan_result()
    exec_response = _make_agent_response("done")

    orch = Orchestrator(config)  # no event_bus
    with (
        patch.object(orch._planner, "run", new=AsyncMock(return_value=plan_response)),
        patch.object(orch, "_get_executor") as mock_get_exec,
    ):
        mock_exec = MagicMock()
        mock_exec.run = AsyncMock(return_value=exec_response)
        mock_get_exec.return_value = mock_exec

        # Must not raise
        result = await orch.run("hi", "test_session")
    assert result.content == "done"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py::test_orchestrator_emits_events_in_correct_order -v
```
Expected: `FAILED` — `TypeError: __init__() got unexpected keyword argument 'event_bus'`

- [ ] **Step 3: Implement orchestrator instrumentation**

In `src/kore/agents/orchestrator.py`:

**3a.** Add import at the top:
```python
from datetime import datetime, timezone
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from kore.gateway.event_bus import EventBus
```

**3b.** Update `__init__` — add `event_bus` parameter and store it:
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
    ...existing body...
    self._bus = event_bus
```

**3c.** Add `_emit` helper after `__init__`:
```python
async def _emit(self, event: dict) -> None:
    """Emit an event to the event bus if one is configured."""
    if self._bus is not None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        await self._bus.emit(event)
```

**3d.** Update `run()` to emit events. Replace the existing `run()` body with the instrumented version:

```python
async def run(self, message: str, session_id: str) -> AgentResponse:
    """Run the full pipeline: plan → execute steps → extract memories → save session."""
    await self._emit({"type": "session_start", "session_id": session_id, "message": message})

    try:
        buffer = SessionBuffer.load(session_id)

        context_prefix = await self._build_memory_context(message)
        planner_message = f"{context_prefix}{message}" if context_prefix else message

        kore_deps = KoreDeps(
            config=self._config,
            core_memory=self._core_memory,
            event_log=self._event_log,
            retriever=self._retriever,
        )

        plan_response = await self._planner.run(
            planner_message,
            deps=kore_deps,
            message_history=buffer.history(),
        )
        plan: PlanResult | None = plan_response.output

        if not plan or not plan.steps:
            response = AgentResponse(
                content="I wasn't sure how to handle that. Could you rephrase?",
                tool_calls=[],
                model_used=self._config.agents.planner.model,
            )
            await self._emit({"type": "session_done", "session_id": session_id, "response": response.content})
            return response

        context = message
        last_response: AgentResponse | None = None
        for step_index, step in enumerate(plan.steps):
            executor, safe_instruction = self._resolve_step(step.executor, step.instruction, message)
            executor_name = step.executor if step.executor in self._config.agents.executors else "general"
            executor_model = self._config.agents.executors.get(executor_name, self._config.agents.executors.get("general"))

            await self._emit({
                "type": "plan_result",
                "session_id": session_id,
                "step_index": step_index,
                "executor": executor_name,
                "instruction": safe_instruction,
                "reasoning": plan.reasoning,
            })
            await self._emit({
                "type": "executor_start",
                "session_id": session_id,
                "step_index": step_index,
                "executor_name": executor_name,
                "model": executor_model.model if executor_model else "unknown",
            })

            instruction = f"{safe_instruction}\n\nContext from previous step:\n{context}"
            last_response = await executor.run(instruction, deps=kore_deps)
            context = last_response.content

            # Emit tool calls as a batch (pydantic-ai exposes them post-run)
            for tc in last_response.tool_calls:
                await self._emit({
                    "type": "tool_call",
                    "session_id": session_id,
                    "step_index": step_index,
                    "tool_name": tc.name,
                    "args": tc.args,
                })
                result_str = str(tc.result) if tc.result is not None else ""
                await self._emit({
                    "type": "tool_result",
                    "session_id": session_id,
                    "step_index": step_index,
                    "tool_name": tc.name,
                    "result": result_str[:500],
                })

            await self._emit({
                "type": "executor_done",
                "session_id": session_id,
                "step_index": step_index,
                "content_preview": last_response.content[:200],
            })

        assert last_response is not None
        buffer.append(role="user", content=message)
        buffer.append(role="assistant", content=last_response.content)
        await buffer.compact_if_needed(self._config)
        buffer.save()

        if self._extraction_agent is not None:
            try:
                await self._extraction_agent.extract_and_store(buffer.history())
            except Exception as exc:
                logger.warning("Post-conversation extraction failed: %s", exc)

        await self._emit({"type": "session_done", "session_id": session_id, "response": last_response.content})
        return last_response

    except Exception as exc:
        await self._emit({"type": "session_error", "session_id": session_id, "error": str(exc)})
        raise
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py -v -k "orchestrator"
```
Expected: all 3 orchestrator tests `PASSED`

- [ ] **Step 5: Run full orchestrator tests to confirm no regressions**

```bash
cd /root/kore-ai && python -m pytest tests/test_orchestrator.py -v
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd /root/kore-ai && git add src/kore/agents/orchestrator.py tests/test_session_debugger.py
git commit -m "feat: instrument orchestrator with event bus emission"
```

---

## Task 4: WebSocket /ws/sessions

**Files:**
- Modify: `src/kore/gateway/routes_ws.py`
- Modify: `tests/test_session_debugger.py` (append WebSocket tests)

The endpoint must return HTTP 503 **before** calling `websocket.accept()` when `app.state.event_bus is None`. After accepting, it replays recent events, then streams live events as JSON text frames.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_debugger.py`:

```python
# ── WebSocket /ws/sessions ──────────────────────────────────────────────────

def test_ws_sessions_returns_503_when_event_bus_is_none():
    """WebSocket upgrade to /ws/sessions returns 503 when event_bus is None.

    FastAPI WebSocket routes only match on WS upgrade requests (scope type
    "websocket"), not plain HTTP GETs. Use Starlette's TestClient.websocket_connect()
    which issues a proper upgrade; when the server rejects before accept() with a 503
    Response, Starlette raises WebSocketDenialResponse with status_code=503.
    """
    import pytest
    from starlette.testclient import TestClient

    app = _make_gateway_app(event_bus=None)
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect("/ws/sessions"):
            pass
    assert exc_info.value.status_code == 503


def test_ws_sessions_replays_recent_events_on_connect():
    """On connect, the last 200 events from the ring buffer are sent as JSON frames.

    Must be a sync test: TestClient.websocket_connect() is synchronous.
    Pre-populate the EventBus using asyncio.run() so we don't call
    run_until_complete() on an already-running loop.
    """
    import asyncio
    import json
    from kore.gateway.event_bus import EventBus
    from starlette.testclient import TestClient

    event_bus = EventBus()

    async def _populate():
        for i in range(3):
            await event_bus.emit({"type": "session_start", "session_id": f"s{i}", "ts": "t"})
    asyncio.run(_populate())

    app = _make_gateway_app(event_bus=event_bus)
    client = TestClient(app)
    received = []
    with client.websocket_connect("/ws/sessions") as ws:
        for _ in range(3):
            received.append(json.loads(ws.receive_text()))
        ws.close()

    assert len(received) == 3
    assert all(e["type"] == "session_start" for e in received)


def _make_gateway_app(event_bus=None):
    from kore.config import LLMConfig, KoreConfig
    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    from kore.gateway.server import create_app
    return create_app(config, event_bus=event_bus)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py::test_ws_sessions_returns_503_when_event_bus_is_none tests/test_session_debugger.py::test_ws_sessions_replays_recent_events_on_connect -v
```
Expected: `FAILED` — `TypeError: create_app() got an unexpected keyword argument 'event_bus'`

(Note: These tests pass only after Task 6 wires `event_bus` into `create_app`. For now, focus on getting the WebSocket handler logic right.)

- [ ] **Step 3: Implement /ws/sessions in routes_ws.py**

Append to `src/kore/gateway/routes_ws.py`:

```python
import json

from fastapi import Response


@router.websocket("/ws/sessions")
async def websocket_sessions(websocket: WebSocket) -> None:
    """Stream live session trace events to connected clients.

    Returns HTTP 503 before the WebSocket handshake if session_tracing is
    disabled (event_bus is None). On connect, replays the last 200 events
    from the ring buffer, then streams live events until disconnect.
    """
    event_bus = websocket.app.state.event_bus
    if event_bus is None:
        await websocket.close(code=1013)  # will be sent as HTTP 503 pre-handshake
        return

    await websocket.accept()
    queue = event_bus.subscribe()
    # Replay recent events for late-joining clients
    for event in event_bus.recent(200):
        await websocket.send_text(json.dumps(event))
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket /ws/sessions closed with unexpected error", exc_info=True)
    finally:
        event_bus.unsubscribe(queue)
```

**Important:** FastAPI's WebSocket route does not support returning an HTTP 503 response before handshake via `websocket.close()` — a pre-handshake 503 requires an HTTP response, not a WS close frame. The correct implementation is:

```python
@router.websocket("/ws/sessions")
async def websocket_sessions(websocket: WebSocket) -> None:
    event_bus = websocket.app.state.event_bus
    if event_bus is None:
        # Reject before handshake — send HTTP 503 response
        response = Response(status_code=503, content="Session tracing is disabled")
        await response(websocket.scope, websocket.receive, websocket.send)
        return

    await websocket.accept()
    queue = event_bus.subscribe()
    for event in event_bus.recent(200):
        await websocket.send_text(json.dumps(event))
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket /ws/sessions closed with unexpected error", exc_info=True)
    finally:
        event_bus.unsubscribe(queue)
```

Also add `import json` and `from fastapi import Response` at the top of the file.

- [ ] **Step 4: Run the WebSocket tests (after Task 6 `create_app` update)**

These tests depend on `create_app` accepting `event_bus` — run them together after Task 6 is complete:

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py -v -k "ws_sessions"
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
cd /root/kore-ai && git add src/kore/gateway/routes_ws.py tests/test_session_debugger.py
git commit -m "feat: add /ws/sessions WebSocket endpoint for live trace streaming"
```

---

## Task 5: REST /api/sessions Endpoints

**Files:**
- Modify: `src/kore/gateway/routes_api.py`
- Modify: `tests/test_session_debugger.py` (append REST tests)

Sessions are stored as `~/.kore/workspace/sessions/{session_id}.json` by `SessionBuffer`. The REST endpoints read these files. Use the module-level `_sessions_dir()` from `kore.session.buffer`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_debugger.py`:

```python
# ── REST /api/sessions ──────────────────────────────────────────────────────

@pytest.fixture
def sessions_app(kore_home):
    """Gateway app pointed at the tmp kore_home for REST session tests."""
    return _make_gateway_app()


@pytest.mark.asyncio
async def test_get_sessions_returns_empty_list_when_no_sessions(sessions_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=sessions_app), base_url="http://test") as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_sessions_lists_sessions_sorted_newest_first(kore_home, sessions_app):
    import json
    from kore.session.buffer import _sessions_dir

    sess_dir = _sessions_dir()
    sess_dir.mkdir(parents=True, exist_ok=True)

    # Write two session files with different created_at
    older = {
        "session_id": "session_a",
        "created_at": "2026-03-20T10:00:00+00:00",
        "summary": None,
        "turns": [
            {"role": "user", "content": "Hello older", "timestamp": "2026-03-20T10:00:00+00:00"},
            {"role": "assistant", "content": "Hi", "timestamp": "2026-03-20T10:00:01+00:00"},
        ],
    }
    newer = {
        "session_id": "session_b",
        "created_at": "2026-03-21T12:00:00+00:00",
        "summary": None,
        "turns": [
            {"role": "user", "content": "Hello newer", "timestamp": "2026-03-21T12:00:00+00:00"},
            {"role": "assistant", "content": "Hi", "timestamp": "2026-03-21T12:00:01+00:00"},
        ],
    }
    (sess_dir / "session_a.json").write_text(json.dumps(older))
    (sess_dir / "session_b.json").write_text(json.dumps(newer))

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=sessions_app), base_url="http://test") as client:
        resp = await client.get("/api/sessions")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["session_id"] == "session_b"  # newest first
    assert data[1]["session_id"] == "session_a"
    assert data[0]["turn_count"] == 1  # 2 turns // 2
    assert data[0]["last_message"] == "Hello newer"


@pytest.mark.asyncio
async def test_get_session_by_id_returns_full_data(kore_home, sessions_app):
    import json
    from kore.session.buffer import _sessions_dir

    sess_dir = _sessions_dir()
    sess_dir.mkdir(parents=True, exist_ok=True)
    session_data = {
        "session_id": "my_session",
        "created_at": "2026-03-21T12:00:00+00:00",
        "summary": None,
        "turns": [
            {"role": "user", "content": "Hello", "timestamp": "2026-03-21T12:00:00+00:00"},
            {"role": "assistant", "content": "Hi there", "timestamp": "2026-03-21T12:00:01+00:00"},
        ],
    }
    (sess_dir / "my_session.json").write_text(json.dumps(session_data))

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=sessions_app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/my_session")

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "my_session"
    assert len(data["turns"]) == 2
    assert data["turns"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_get_session_by_id_returns_404_for_missing_session(sessions_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=sessions_app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py -v -k "sessions" --ignore-glob="*ws*"
```
Expected: `FAILED` — 404 for `/api/sessions` (route not registered yet)

- [ ] **Step 3: Implement REST endpoints in routes_api.py**

Append to `src/kore/gateway/routes_api.py` (after the `/api/logs` section):

```python
# ── /api/sessions ─────────────────────────────────────────────────────────────

@router.get("/sessions")
async def get_sessions() -> list[dict[str, Any]]:
    """List all sessions sorted newest-first.

    Reads from ~/.kore/workspace/sessions/*.json via SessionBuffer's _sessions_dir().
    Returns [] if the directory does not exist (fresh install, no sessions yet).
    """
    from kore.session.buffer import _sessions_dir

    sess_dir = _sessions_dir()
    if not sess_dir.exists():
        return []

    sessions = []
    for path in sess_dir.glob("*.json"):
        try:
            import json as _json
            data = _json.loads(path.read_text())
            turns = data.get("turns", [])
            user_turns = [t for t in turns if t.get("role") == "user"]
            last_message = (user_turns[-1]["content"][:100] if user_turns else "")
            sessions.append({
                "session_id": data["session_id"],
                "created_at": data["created_at"],
                "turn_count": len(turns) // 2,
                "last_message": last_message,
            })
        except Exception:
            logger.warning("Skipping corrupt session file: %s", path)

    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return sessions


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Return full session content by session_id. Returns 404 if not found."""
    from kore.session.buffer import _sessions_dir
    import json as _json

    path = _sessions_dir() / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    try:
        return _json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to read session file") from exc
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py -v -k "get_session"
```
Expected: all 4 REST tests `PASSED`

- [ ] **Step 5: Commit**

```bash
cd /root/kore-ai && git add src/kore/gateway/routes_api.py tests/test_session_debugger.py
git commit -m "feat: add GET /api/sessions and GET /api/sessions/{id} endpoints"
```

---

## Task 6: Wiring — server.py + main.py

**Files:**
- Modify: `src/kore/gateway/server.py`
- Modify: `src/kore/main.py`
- Modify: `tests/test_session_debugger.py` (append wiring test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_session_debugger.py`:

```python
# ── Wiring ──────────────────────────────────────────────────────────────────

def test_create_app_with_event_bus_none_stores_none_in_state():
    """create_app(config, event_bus=None) must set app.state.event_bus to None."""
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config, event_bus=None)
    assert app.state.event_bus is None


def test_create_app_with_event_bus_stores_instance():
    """create_app(config, event_bus=bus) must store the bus in app.state."""
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app
    from kore.gateway.event_bus import EventBus

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    bus = EventBus()
    app = create_app(config, event_bus=bus)
    assert app.state.event_bus is bus
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py::test_create_app_with_event_bus_none_stores_none_in_state -v
```
Expected: `FAILED` — `TypeError: create_app() got an unexpected keyword argument 'event_bus'`

- [ ] **Step 3: Update server.py**

Add `event_bus` to `create_app`'s TYPE_CHECKING imports:
```python
if TYPE_CHECKING:
    ...
    from kore.gateway.event_bus import EventBus
```

Add parameter and state assignment in `create_app`:
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
    app.state.event_bus = event_bus  # add after existing app.state assignments
```

- [ ] **Step 4: Update main.py**

In `src/kore/main.py`, after `config = load_config()`, add EventBus instantiation:

```python
from kore.gateway.event_bus import EventBus
event_bus: EventBus | None = EventBus() if config.debug.session_tracing else None
```

Pass it to `Orchestrator`:
```python
raw_orchestrator = Orchestrator(config, event_bus=event_bus)
```

Pass it to `create_app`:
```python
app = create_app(
    config,
    queue=queue,
    scheduler=scheduler,
    orchestrator=raw_orchestrator,
    telegram_channel=telegram_channel,
    event_bus=event_bus,   # new
)
```

- [ ] **Step 5: Run all session debugger tests**

```bash
cd /root/kore-ai && python -m pytest tests/test_session_debugger.py -v
```
Expected: all tests pass (including the WebSocket tests from Task 4 that were previously blocked by the missing `create_app` parameter)

- [ ] **Step 6: Run full test suite to confirm no regressions**

```bash
cd /root/kore-ai && python -m pytest tests/ -v --tb=short
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
cd /root/kore-ai && git add src/kore/gateway/server.py src/kore/main.py tests/test_session_debugger.py
git commit -m "feat: wire EventBus through create_app and main.py"
```

---

## Task 7: UI Sessions Page

**Files:**
- Create: `ui/src/pages/Sessions.jsx`
- Modify: `ui/src/App.jsx`

No automated tests — manual verification against the spec mockup.

The page has three states:
1. **No session selected** — right panel shows placeholder.
2. **Session selected (historical)** — right panel shows persisted turns from `GET /api/sessions/{id}`.
3. **Live session** — incoming WebSocket events update the active session's trace in real time.

WebSocket events use `session_id` to route to the correct session. The UI groups events by session and `step_index` to build the trace block per turn.

- [ ] **Step 1: Create Sessions.jsx**

Create `ui/src/pages/Sessions.jsx`:

```jsx
import { useEffect, useRef, useState } from 'react'

const WS_PROTO = location.protocol === 'https:' ? 'wss' : 'ws'

function relativeTime(isoStr) {
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function TraceBlock({ traceEvents }) {
  const [open, setOpen] = useState(false)
  const [expandedTools, setExpandedTools] = useState(new Set())

  if (!traceEvents || traceEvents.length === 0) return null

  const planEvent = traceEvents.find(e => e.type === 'plan_result')
  const toolPairs = []
  const toolCalls = traceEvents.filter(e => e.type === 'tool_call')
  toolCalls.forEach(tc => {
    const result = traceEvents.find(e => e.type === 'tool_result' && e.tool_name === tc.tool_name)
    toolPairs.push({ call: tc, result })
  })

  const toggleTool = idx => setExpandedTools(prev => {
    const next = new Set(prev)
    next.has(idx) ? next.delete(idx) : next.add(idx)
    return next
  })

  return (
    <div className="trace-block">
      <div className="trace-header" onClick={() => setOpen(o => !o)}>
        <span className="trace-toggle">{open ? '▼' : '▶'}</span>
        {planEvent && <span className="trace-executor">{planEvent.executor}</span>}
        {toolPairs.length > 0 && (
          <span className="trace-tools-summary">{toolPairs.length} tool{toolPairs.length > 1 ? 's' : ''}</span>
        )}
      </div>
      {open && (
        <div className="trace-body">
          {planEvent && (
            <div className="trace-plan-row">
              <span className="trace-label">Planner</span>
              <span className="trace-reasoning">{planEvent.reasoning}</span>
            </div>
          )}
          {toolPairs.map(({ call, result }, idx) => (
            <div key={idx} className="trace-tool-row" onClick={() => toggleTool(idx)}>
              <span className="trace-tool-name">{expandedTools.has(idx) ? '▼' : '▶'} {call.tool_name}</span>
              {expandedTools.has(idx) && (
                <div className="trace-tool-detail">
                  <div className="trace-tool-args">
                    <span className="trace-label">Args</span>
                    <pre>{JSON.stringify(call.args, null, 2)}</pre>
                  </div>
                  {result && (
                    <div className="trace-tool-result">
                      <span className="trace-label">Result</span>
                      <pre>{result.result}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Timeline({ turns, traceByStep, liveEvents, selectedSessionId }) {
  const bottomRef = useRef(null)

  // Group live events by step_index
  const liveByStep = {}
  for (const e of liveEvents) {
    if (e.step_index !== undefined) {
      if (!liveByStep[e.step_index]) liveByStep[e.step_index] = []
      liveByStep[e.step_index].push(e)
    }
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, liveEvents])

  if (turns.length === 0 && liveEvents.length === 0) {
    return <div className="empty-state">No turns yet</div>
  }

  // Build pairs from persisted turns
  const pairs = []
  for (let i = 0; i < turns.length; i += 2) {
    const user = turns[i]
    const asst = turns[i + 1]
    const stepIndex = i / 2
    pairs.push({ user, asst, stepIndex, trace: traceByStep[stepIndex] || [] })
  }

  // Check if there's a live turn in progress (session_start received but no session_done yet)
  const hasLiveSessionStart = liveEvents.some(e => e.type === 'session_start' && e.session_id === selectedSessionId)
  const hasLiveSessionDone = liveEvents.some(e => e.type === 'session_done' && e.session_id === selectedSessionId)
  const isLive = hasLiveSessionStart && !hasLiveSessionDone

  return (
    <div className="timeline">
      {pairs.map(({ user, asst, stepIndex, trace }) => (
        <div key={stepIndex} className="turn-pair">
          {user && (
            <div className="bubble user-bubble">{user.content}</div>
          )}
          <TraceBlock traceEvents={trace} />
          {asst && (
            <div className="bubble asst-bubble">{asst.content}</div>
          )}
        </div>
      ))}

      {isLive && (
        <div className="turn-pair live-turn">
          {liveEvents.find(e => e.type === 'session_start' && e.session_id === selectedSessionId) && (
            <div className="bubble user-bubble">
              {liveEvents.find(e => e.type === 'session_start' && e.session_id === selectedSessionId)?.message}
            </div>
          )}
          <TraceBlock traceEvents={Object.values(liveByStep).flat()} />
          <div className="bubble asst-bubble live-pending">
            <span className="pulse-dot" /> thinking…
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}

export default function Sessions() {
  const [sessions, setSessions] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [sessionData, setSessionData] = useState(null)
  const [liveEvents, setLiveEvents] = useState([])
  const [wsStatus, setWsStatus] = useState('connecting') // 'connecting' | 'live' | 'unavailable'
  const wsRef = useRef(null)

  // Load session list
  useEffect(() => {
    fetch('/api/sessions')
      .then(r => r.json())
      .then(setSessions)
      .catch(() => {})
  }, [])

  // Connect WebSocket for live events
  useEffect(() => {
    const ws = new WebSocket(`${WS_PROTO}://${location.host}/ws/sessions`)
    wsRef.current = ws
    ws.onopen = () => setWsStatus('live')
    ws.onmessage = e => {
      try {
        const event = JSON.parse(e.data)
        setLiveEvents(prev => [...prev.slice(-500), event])
        // If a new session appears in live events, refresh the session list
        if (event.type === 'session_done') {
          fetch('/api/sessions').then(r => r.json()).then(setSessions).catch(() => {})
        }
      } catch {}
    }
    ws.onerror = () => setWsStatus('unavailable')
    ws.onclose = e => {
      if (e.code === 1013 || e.code === 503) setWsStatus('unavailable')
    }
    return () => ws.close()
  }, [])

  // Load selected session detail
  useEffect(() => {
    if (!selectedId) { setSessionData(null); return }
    fetch(`/api/sessions/${selectedId}`)
      .then(r => r.ok ? r.json() : null)
      .then(setSessionData)
      .catch(() => setSessionData(null))
  }, [selectedId])

  const turns = sessionData?.turns || []
  const liveForSession = liveEvents.filter(e => e.session_id === selectedId)

  return (
    <>
      <div className="page-header">
        <div className="page-title">Sessions</div>
        <div className="page-sub">
          Execution trace for each request
          {wsStatus === 'live' && <span className="ws-badge live">● live</span>}
          {wsStatus === 'unavailable' && (
            <span className="ws-badge unavailable" title="Enable debug.session_tracing in config to see live traces">
              Live trace unavailable — enable debug.session_tracing in config
            </span>
          )}
        </div>
      </div>

      <div className="sessions-layout">
        {/* Sidebar */}
        <div className="sessions-sidebar">
          {sessions.length === 0 && <div className="empty-state">No sessions yet</div>}
          {sessions.map(s => (
            <div
              key={s.session_id}
              className={`session-item${selectedId === s.session_id ? ' active' : ''}`}
              onClick={() => setSelectedId(s.session_id)}
            >
              <div className="session-id">{s.session_id}</div>
              <div className="session-meta">
                <span>{relativeTime(s.created_at)}</span>
                <span>{s.turn_count} turn{s.turn_count !== 1 ? 's' : ''}</span>
              </div>
              <div className="session-preview">{s.last_message}</div>
            </div>
          ))}
        </div>

        {/* Detail panel */}
        <div className="sessions-detail">
          {!selectedId && (
            <div className="empty-state">Select a session to view its trace</div>
          )}
          {selectedId && (
            <Timeline
              turns={turns}
              traceByStep={{}}
              liveEvents={liveForSession}
              selectedSessionId={selectedId}
            />
          )}
        </div>
      </div>
    </>
  )
}
```

- [ ] **Step 2: Add CSS for Sessions page to index.css**

Append to `ui/src/index.css`:

```css
/* ── Sessions page ───────────────────────────────────────────────────── */
.sessions-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 0;
  height: calc(100vh - 120px);
  overflow: hidden;
}
.sessions-sidebar {
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 8px 0;
}
.session-item {
  padding: 10px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.15s;
}
.session-item:hover { background: var(--hover); }
.session-item.active { border-left-color: var(--accent); background: var(--hover); }
.session-id { font-size: 11px; font-weight: 600; color: var(--text); font-family: monospace; }
.session-meta { font-size: 10px; color: var(--muted); display: flex; gap: 8px; margin: 2px 0; }
.session-preview { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sessions-detail { overflow-y: auto; padding: 16px 20px; }
.timeline { display: flex; flex-direction: column; gap: 12px; }
.turn-pair { display: flex; flex-direction: column; gap: 6px; }
.bubble { max-width: 70%; padding: 10px 14px; border-radius: 10px; font-size: 13px; line-height: 1.5; }
.user-bubble { align-self: flex-end; background: var(--accent); color: #fff; }
.asst-bubble { align-self: flex-start; background: var(--card); color: var(--text); border: 1px solid var(--border); }
.live-pending { color: var(--muted); font-style: italic; }
.trace-block { border-left: 2px solid var(--border); padding: 4px 0 4px 10px; margin: 2px 0; }
.trace-header { cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--muted); user-select: none; }
.trace-executor { font-weight: 600; color: var(--accent); }
.trace-tools-summary { color: var(--muted); }
.trace-body { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; }
.trace-plan-row { font-size: 11px; color: var(--muted); display: flex; gap: 6px; }
.trace-tool-row { cursor: pointer; font-size: 11px; padding: 3px 0; color: var(--text); }
.trace-tool-name { font-family: monospace; }
.trace-tool-detail { margin: 4px 0 4px 12px; display: flex; flex-direction: column; gap: 4px; }
.trace-tool-args pre, .trace-tool-result pre { margin: 2px 0; font-size: 10px; background: var(--bg); padding: 6px; border-radius: 4px; overflow-x: auto; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }
.trace-label { font-size: 10px; font-weight: 600; color: var(--muted); text-transform: uppercase; margin-right: 6px; }
.ws-badge { font-size: 10px; margin-left: 8px; padding: 2px 6px; border-radius: 9px; }
.ws-badge.live { background: #1a3a1a; color: #4caf50; }
.ws-badge.unavailable { background: var(--card); color: var(--muted); }
.pulse-dot { display: inline-block; width: 6px; height: 6px; background: var(--accent); border-radius: 50%; margin-right: 4px; animation: pulse 1.2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
```

- [ ] **Step 3: Update App.jsx to add Sessions route**

In `ui/src/App.jsx`:

**3a.** Add import at the top with other page imports:
```jsx
import Sessions from './pages/Sessions.jsx'
```

**3b.** Add to `MAIN_NAV` array (after Logs entry):
```jsx
{ to: '/sessions', label: 'Sessions', icon: '◎', badge: 'debug' },
```

**3c.** Add route inside `<Routes>`:
```jsx
<Route path="/sessions" element={<Sessions />} />
```

- [ ] **Step 4: Verify the UI builds**

```bash
cd /root/kore-ai/ui && npm run build 2>&1 | tail -20
```
Expected: `✓ built in` — no errors

- [ ] **Step 5: Commit**

```bash
cd /root/kore-ai && git add ui/src/pages/Sessions.jsx ui/src/App.jsx ui/src/index.css
git commit -m "feat: add Sessions page with live trace timeline and WebSocket stream"
```

---

## Final Verification

- [ ] **Run the complete test suite**

```bash
cd /root/kore-ai && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all tests pass, no regressions.

- [ ] **Run the UI build**

```bash
cd /root/kore-ai/ui && npm run build 2>&1 | tail -5
```
Expected: clean build.

- [ ] **Manual smoke test (optional — requires running instance)**

1. Set `"debug": {"session_tracing": true}` in `~/.kore/config.json`
2. Start Kore: `python -m kore gateway`
3. Open `http://localhost:8000/sessions`
4. Send a message via Telegram or `POST /api/message`
5. Verify the session appears in the sidebar and the trace block shows planner + tool calls live
6. Unset `session_tracing`, restart, verify `/sessions` shows historical data only and the "Live trace unavailable" note appears
