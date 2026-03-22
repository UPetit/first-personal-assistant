# Phase 7 — Integration & Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured JSON logging, fill the integration test gap (HTTP + real orchestrator pipeline in one test), and cover all remaining failure paths (consumer loop, rate-limit window recovery, compaction/token limit, reply failure).

**Architecture:** Three independent tasks. Task 1 adds a `JsonFormatter` + `configure_logging()` helper and updates `_cli_main()`. Tasks 2 and 3 create `tests/test_integration.py`, using the same monkeypatch pattern from `test_orchestrator.py` (inject TestModel-backed planner/executor into a real `Orchestrator`) then wire it into the FastAPI app via `create_app()` — so a single test exercises the HTTP layer **and** the real orchestrator pipeline together for the first time.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, httpx ASGITransport, pydantic-ai TestModel, python-json-logger ≥ 2.0, < 3 (v3 restructured imports)

**Critical note on `Message` dataclass:** `Message` fields are `text`, `channel`, `session_id`, `user_id`, `reply`. There is **no** `chat_id` field. All test constructions must use `user_id="api"` (or `"cron"`), not `chat_id=0`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `python-json-logger>=2.0,<3` to dependencies |
| `src/kore/logging_config.py` | Create | `JsonFormatter`, `configure_logging(level, json_format)` |
| `src/kore/main.py` | Modify | Call `configure_logging()` in `_cli_main()` instead of `logging.basicConfig()` |
| `tests/test_logging_config.py` | Create | Verify JSON log output and field contract |
| `tests/test_integration.py` | Create | Full-stack integration tests (HTTP+orchestrator) and consumer loop tests |

---

## Task 1: Structured JSON Logging

**Files:**
- Modify: `pyproject.toml`
- Create: `src/kore/logging_config.py`
- Modify: `src/kore/main.py` (lines around `_cli_main`)
- Create: `tests/test_logging_config.py`

---

- [ ] **Step 1: Write failing tests**

Create `tests/test_logging_config.py`:

```python
from __future__ import annotations

import io
import json
import logging


def _capture_json_log(level: int, message: str) -> dict:
    """Emit one log record through a JsonFormatter and return the parsed JSON."""
    from kore.logging_config import JsonFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    buf = io.StringIO()
    handler.stream = buf

    logger = logging.getLogger("kore_test_json_" + str(level))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    logger.log(level, message)
    return json.loads(buf.getvalue().strip())


def test_json_formatter_produces_valid_json():
    data = _capture_json_log(logging.INFO, "hello world")
    assert isinstance(data, dict)


def test_json_formatter_contains_required_fields():
    data = _capture_json_log(logging.WARNING, "test message")
    assert "timestamp" in data
    assert "level" in data
    assert "logger" in data
    assert "message" in data


def test_json_formatter_level_name():
    data = _capture_json_log(logging.ERROR, "oops")
    assert data["level"] == "ERROR"


def test_json_formatter_message_content():
    data = _capture_json_log(logging.INFO, "specific content")
    assert data["message"] == "specific content"


def test_configure_logging_adds_root_handler():
    from kore.logging_config import configure_logging
    import logging as _logging

    root = _logging.getLogger()
    before = len(root.handlers)
    configure_logging(level=logging.DEBUG, json_format=False)
    assert len(root.handlers) > before
    # Restore to avoid polluting other tests
    for h in root.handlers[before:]:
        root.removeHandler(h)
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_logging_config.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'kore.logging_config'`

- [ ] **Step 3: Add `python-json-logger` to pyproject.toml**

In `[project]` → `dependencies`, add:
```toml
"python-json-logger>=2.0,<3",
```

The `<3` upper bound prevents version 3.x which restructured imports to `pythonjsonlogger.core`.

Install: `pip install -e ".[dev]" -q`

- [ ] **Step 4: Create `src/kore/logging_config.py`**

```python
from __future__ import annotations

import logging

from pythonjsonlogger.jsonlogger import JsonFormatter as _BaseJsonFormatter


class JsonFormatter(_BaseJsonFormatter):
    """JSON log formatter with a consistent field contract.

    Every record produces: ``timestamp``, ``level``, ``logger``, ``message``.
    Additional fields (``exc_info``, ``stack_info``) are included when present.
    """

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # Normalise to the project field contract
        if "asctime" not in log_record:
            log_record["timestamp"] = self.formatTime(record, self.datefmt)
        else:
            log_record["timestamp"] = log_record.pop("asctime")
        log_record["level"] = log_record.pop("levelname", record.levelname)
        log_record["logger"] = log_record.pop("name", record.name)
        log_record["message"] = log_record.pop("message", record.getMessage())


def configure_logging(
    level: int = logging.INFO,
    *,
    json_format: bool = True,
) -> None:
    """Configure the root logger with a stream handler.

    Args:
        level: Logging level (e.g. ``logging.INFO``).
        json_format: When True use ``JsonFormatter``; otherwise use a
            human-readable format suitable for development/testing.
    """
    handler = logging.StreamHandler()
    if json_format:
        handler.setFormatter(JsonFormatter("%(timestamp)s %(level)s %(logger)s %(message)s"))
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
```

- [ ] **Step 5: Update `src/kore/main.py` — replace `logging.basicConfig` calls**

Read `src/kore/main.py` first. There are two `logging.basicConfig(level=logging.INFO)` calls: one in `_cli_main()` (~line 153) and one in the `if __name__ == "__main__"` block (~line 161).

Replace both:

*Before:*
```python
logging.basicConfig(level=logging.INFO)
```

*After:*
```python
from kore.logging_config import configure_logging
configure_logging(level=logging.INFO, json_format=False)
```

Use `json_format=False` for the CLI entry point (human-readable in development).

- [ ] **Step 6: Run tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_logging_config.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 7: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

- [ ] **Step 8: Commit**

```bash
cd /root/kore-ai
git add pyproject.toml src/kore/logging_config.py src/kore/main.py tests/test_logging_config.py
git commit -m "feat: structured JSON logging — JsonFormatter + configure_logging()"
```

---

## Task 2: Integration Tests — Happy Path

**Files:**
- Create: `tests/test_integration.py`

This task creates the integration test file with happy-path scenarios. The gap being filled: `test_gateway.py` uses a **mock** orchestrator; `test_orchestrator.py` uses a real orchestrator **without** the HTTP layer. These tests exercise both together for the first time.

The monkeypatch pattern is copied directly from `test_orchestrator.py`: patch `kore.agents.orchestrator.create_planner` and `kore.agents.orchestrator.create_executor` to inject TestModel-backed agents.

---

- [ ] **Step 1: Write failing tests**

Create `tests/test_integration.py`:

```python
from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from pydantic_ai.models.test import TestModel

from kore.agents.base import BaseAgent
from kore.agents.orchestrator import Orchestrator
from kore.agents.planner import PlanResult
from kore.channels.base import Message, noop_reply
from kore.config import (
    AgentsConfig,
    ExecutorConfig,
    KoreConfig,
    LLMConfig,
    SecurityConfig,
)
from kore.gateway.queue import MessageQueue
from kore.llm.types import AgentResponse
from kore.main import _OrchestratorAdapter, _consume


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def kore_home(tmp_path, monkeypatch):
    import kore.conversation.buffer as buf_mod
    import kore.config as config_mod

    monkeypatch.setattr(config_mod, "KORE_HOME", tmp_path)
    monkeypatch.setattr(buf_mod, "KORE_HOME", tmp_path)
    return tmp_path


@pytest.fixture
def integration_config():
    """Minimal KoreConfig for integration tests (auth disabled, single executor)."""
    from kore.config import ConversationConfig

    planner_cfg = ExecutorConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt_file="planner.md",
        tools=[],
        description="Planner",
    )
    executor_cfg = ExecutorConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt_file="general.md",
        tools=[],
        description="General executor",
    )
    return KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
        security=SecurityConfig(api_auth_enabled=False),
        agents=AgentsConfig(planner=planner_cfg, executors={"general": executor_cfg}),
        conversation=ConversationConfig(),
    )


def _mock_planner(steps: list[dict]) -> BaseAgent:
    """Return a BaseAgent backed by TestModel that produces a fixed plan."""
    model = TestModel(custom_output_args={
        "intent": "test intent",
        "reasoning": "test reasoning",
        "steps": steps,
    })
    return BaseAgent(model, "test:planner", "planner", result_type=PlanResult)


def _mock_executor(content: str = "Integration response") -> BaseAgent:
    """Return a BaseAgent whose run() is an AsyncMock returning fixed content."""
    agent = BaseAgent(TestModel(), "test:executor", "executor")
    agent.run = AsyncMock(return_value=AgentResponse(
        content=content, tool_calls=[], model_used="test:executor"
    ))
    return agent


# ── tests: HTTP + real orchestrator ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_message_full_pipeline(kore_home, integration_config, monkeypatch):
    """POST /api/message exercises the full HTTP → real Orchestrator → response path."""
    planner = _mock_planner([{"executor": "general", "instruction": "handle it"}])
    executor = _mock_executor("full pipeline response")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "hello", "session_id": "int-test-1"})

    assert r.status_code == 200
    assert r.json()["response"] == "full pipeline response"
    assert r.json()["session_id"] == "int-test-1"


@pytest.mark.asyncio
async def test_api_message_session_persisted_to_disk(
    kore_home, integration_config, monkeypatch
):
    """After a message, the conversation buffer file exists on disk."""
    planner = _mock_planner([{"executor": "general", "instruction": "do it"}])
    executor = _mock_executor("saved response")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    session_id = "persist-test-" + str(uuid4())[:8]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/message", json={"text": "remember me", "session_id": session_id})

    conv_file = kore_home / "workspace" / "conversations" / f"{session_id}.json"
    assert conv_file.exists(), f"Expected {conv_file} to exist after a conversation turn"


@pytest.mark.asyncio
async def test_api_message_multi_turn_context(
    kore_home, integration_config, monkeypatch
):
    """Second message in same session succeeds (buffer loaded correctly from disk)."""
    planner = _mock_planner([{"executor": "general", "instruction": "respond"}])
    executor = _mock_executor("turn response")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    session_id = "multi-turn-" + str(uuid4())[:8]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post("/api/message", json={"text": "first", "session_id": session_id})
        r2 = await c.post("/api/message", json={"text": "second", "session_id": session_id})

    assert r1.status_code == 200
    assert r2.status_code == 200


# ── tests: consumer loop + adapter ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestrator_adapter_dispatches_message():
    """_OrchestratorAdapter.run(msg) calls orchestrator.run(text, session_id) and replies."""
    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=AgentResponse(
        content="adapter response", tool_calls=[], model_used="test"
    ))

    adapter = _OrchestratorAdapter(mock_orch)
    replies: list[str] = []

    async def capture_reply(text: str) -> None:
        replies.append(text)

    msg = Message(
        text="test message",
        session_id="adapter-session",
        user_id="api",
        channel="api",
        reply=capture_reply,
    )

    await adapter.run(msg)

    mock_orch.run.assert_called_once_with("test message", "adapter-session")
    assert replies == ["adapter response"]


@pytest.mark.asyncio
async def test_consumer_loop_drains_queue():
    """_consume() pulls one message from the queue and dispatches it to the adapter."""
    queue = MessageQueue()

    mock_adapter = MagicMock()
    mock_adapter.run = AsyncMock()

    msg = Message(
        text="queued message",
        session_id="queue-session",
        user_id="cron",
        channel="cron",
        reply=noop_reply,
    )
    await queue.put(msg)

    task = asyncio.create_task(_consume(queue, mock_adapter))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    mock_adapter.run.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_consumer_loop_handles_orchestrator_exception():
    """_consume() logs orchestrator exceptions and keeps running (does not crash)."""
    queue = MessageQueue()

    crash_count = 0

    class CrashAdapter:
        async def run(self, msg: Message) -> None:
            nonlocal crash_count
            crash_count += 1
            raise RuntimeError("simulated crash")

    msg = Message(
        text="crash trigger",
        session_id="crash-session",
        user_id="api",
        channel="api",
        reply=noop_reply,
    )
    await queue.put(msg)

    task = asyncio.create_task(_consume(queue, CrashAdapter()))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert crash_count == 1  # exception was caught, not propagated
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_integration.py -v 2>&1 | head -30
```

Expected: failures due to `_consume` or `Orchestrator` not being importable (if `kore_home` or `integration_config` have issues). All imports in the file should work — the failures should be test-logic failures, not import errors.

- [ ] **Step 3: Run tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_integration.py -v
```

Expected: all 6 happy-path integration tests pass.

**Debugging notes:**
- If `test_api_message_full_pipeline` fails with `ConfigError: Planner not configured`, verify that `integration_config` sets `agents=AgentsConfig(planner=planner_cfg, ...)`.
- If `test_api_message_session_persisted_to_disk` fails because the file doesn't exist, check the `kore_home` fixture is patching both `kore.config.KORE_HOME` and `kore.conversation.buffer.KORE_HOME` (same as `test_orchestrator.py`).
- If `_consume` is not importable from `kore.main`, it is defined at module scope in `main.py` — check that it wasn't moved inside `main()`.

- [ ] **Step 4: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
cd /root/kore-ai
git add tests/test_integration.py
git commit -m "feat: integration tests — HTTP+orchestrator pipeline, consumer loop, adapter"
```

---

## Task 3: Integration Tests — Failure Paths

**Files:**
- Modify: `tests/test_integration.py` (append 8 failure-path tests)

---

- [ ] **Step 1: Append failure-path tests**

Append this block to `tests/test_integration.py`:

```python
# ── failure paths ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_message_503_when_no_orchestrator():
    """POST /api/message returns 503 when orchestrator is not wired."""
    from kore.gateway.server import create_app

    config = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
        security=SecurityConfig(api_auth_enabled=False),
    )
    app = create_app(config)  # orchestrator=None by default

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "hi"})

    assert r.status_code == 503


@pytest.mark.asyncio
async def test_api_message_500_on_orchestrator_exception(
    kore_home, integration_config, monkeypatch
):
    """POST /api/message returns 500 when orchestrator.run() raises."""
    planner = _mock_planner([{"executor": "general", "instruction": "fail"}])
    executor = _mock_executor()
    executor.run = AsyncMock(side_effect=RuntimeError("simulated LLM failure"))

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/message",
            json={"text": "cause a crash", "session_id": "crash-500"},
        )

    assert r.status_code == 500


@pytest.mark.asyncio
async def test_api_auth_rejected_returns_401():
    """POST /api/message with wrong credentials returns 401 with WWW-Authenticate header."""
    from kore.gateway.server import create_app

    config = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
        security=SecurityConfig(
            api_auth_enabled=True,
            api_username="admin",
            api_password=SecretStr("secret"),
        ),
    )
    app = create_app(config)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "hi"}, auth=("admin", "wrong"))

    assert r.status_code == 401
    assert "basic" in r.headers.get("www-authenticate", "").lower()


@pytest.mark.asyncio
async def test_rate_limit_enforced_after_threshold():
    """After exhausting rate_limit_per_user requests, subsequent requests return 429."""
    from kore.gateway.server import create_app

    config = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
        security=SecurityConfig(
            api_auth_enabled=True,
            api_username="admin",
            api_password=SecretStr("secret"),
            rate_limit_per_user=2,
        ),
    )
    app = create_app(config)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/api/memory", auth=("admin", "secret"))
        r2 = await c.get("/api/memory", auth=("admin", "secret"))
        r3 = await c.get("/api/memory", auth=("admin", "secret"))

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_window_recovery(monkeypatch):
    """After the 60-second window elapses, the rate limit resets and requests pass again."""
    from kore.gateway.server import create_app

    fake_time = [0.0]
    monkeypatch.setattr("kore.gateway.auth.monotonic", lambda: fake_time[0])

    config = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
        security=SecurityConfig(
            api_auth_enabled=True,
            api_username="admin",
            api_password=SecretStr("secret"),
            rate_limit_per_user=1,
        ),
    )
    app = create_app(config)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/api/memory", auth=("admin", "secret"))   # within limit
        r2 = await c.get("/api/memory", auth=("admin", "secret"))   # over limit

        # Advance fake clock past the 60-second window
        fake_time[0] = 61.0

        r3 = await c.get("/api/memory", auth=("admin", "secret"))   # window recovered

    assert r1.status_code == 200
    assert r2.status_code == 429
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_empty_plan_steps_returns_canned_response(
    kore_home, integration_config, monkeypatch
):
    """When planner returns zero steps, the orchestrator returns a canned fallback via HTTP."""
    # Replicate the empty-plan setup from test_orchestrator.py but through the HTTP layer
    canned_plan = PlanResult.__new__(PlanResult)
    object.__setattr__(canned_plan, "intent", "unclear")
    object.__setattr__(canned_plan, "reasoning", "unclear")
    object.__setattr__(canned_plan, "steps", [])

    planner_agent = BaseAgent(TestModel(), "test:planner", "planner", result_type=PlanResult)
    planner_agent.run = AsyncMock(return_value=AgentResponse(
        content="", tool_calls=[], model_used="test:planner", data=canned_plan
    ))

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner_agent)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/message",
            json={"text": "????", "session_id": "empty-plan-session"},
        )

    assert r.status_code == 200
    # Orchestrator returns a canned "rephrase" response when plan has no steps
    assert "rephrase" in r.json()["response"].lower()


@pytest.mark.asyncio
async def test_conversation_compaction_on_token_limit(
    kore_home, integration_config, monkeypatch
):
    """When conversation buffer exceeds token threshold, compaction fires and responses still work."""
    from kore.config import ConversationConfig

    # Force compaction by setting threshold to 1 token (always exceeded after first turn)
    config = integration_config.model_copy(update={
        "conversation": ConversationConfig(compaction_token_threshold=1),
    })

    planner = _mock_planner([{"executor": "general", "instruction": "respond"}])
    executor = _mock_executor("post-compaction response")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    # Mock the compactor so no real LLM call is made during compaction
    mock_compactor = MagicMock()
    mock_compactor.summarise = AsyncMock(return_value="[compacted summary]")
    monkeypatch.setattr(
        "kore.conversation.buffer.Compactor.from_config",
        lambda cfg: mock_compactor,
    )

    orch = Orchestrator(config)

    from kore.gateway.server import create_app
    app = create_app(config, orchestrator=orch)

    session_id = "compact-session-" + str(uuid4())[:8]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post("/api/message", json={"text": "first message", "session_id": session_id})
        r2 = await c.post("/api/message", json={"text": "second message", "session_id": session_id})

    assert r1.status_code == 200
    assert r2.status_code == 200  # Response still works after compaction triggered


@pytest.mark.asyncio
async def test_consumer_loop_reply_failure_does_not_crash():
    """If reply() raises, _OrchestratorAdapter logs a warning; _consume does not crash."""
    queue = MessageQueue()

    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=AgentResponse(
        content="response", tool_calls=[], model_used="test"
    ))

    adapter = _OrchestratorAdapter(mock_orch)

    reply_called = 0

    async def failing_reply(text: str) -> None:
        nonlocal reply_called
        reply_called += 1
        raise IOError("Telegram API down")

    msg = Message(
        text="trigger reply failure",
        session_id="reply-fail",
        user_id="api",
        channel="api",
        reply=failing_reply,
    )
    await queue.put(msg)

    task = asyncio.create_task(_consume(queue, adapter))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # _OrchestratorAdapter caught the IOError (logged as warning) — did not crash
    assert reply_called == 1
```

- [ ] **Step 2: Run failure-path tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_integration.py -v
```

Expected: all 14 tests pass (6 happy-path + 8 failure-path).

**Debugging notes:**
- `test_api_message_500_on_orchestrator_exception`: if you get 200 instead of 500, verify the monkeypatched executor has `side_effect=RuntimeError(...)` (not `return_value`). The exception must propagate through `orchestrator.run()` to `routes_api.post_message` where it is caught as a 500.
- `test_rate_limit_window_recovery`: patches `kore.gateway.auth.monotonic`. If the patch doesn't take effect, verify auth.py uses `from time import monotonic` (not `import time; time.monotonic()`). The former binds the name locally so `monkeypatch.setattr("kore.gateway.auth.monotonic", ...)` is the correct patch target.
- `test_conversation_compaction_on_token_limit`: patches `kore.conversation.buffer.Compactor.from_config`. If compaction is skipped (mock not called), increase the threshold — `compaction_token_threshold=1` may not be below the token estimate for a minimal conversation. Try setting it to 0 if 1 doesn't trigger compaction.
- `test_consumer_loop_reply_failure_does_not_crash`: `_OrchestratorAdapter.run()` in `main.py` calls `await msg.reply(response.content)` inside a `try/except Exception` that logs a warning. Verify this exception handler is still in place in `main.py`.

- [ ] **Step 3: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

All tests must pass. Record the final count (should be ≥ 256: 237 existing + 5 logging + 14 integration).

- [ ] **Step 4: Commit**

```bash
cd /root/kore-ai
git add tests/test_integration.py
git commit -m "feat: integration failure-path tests — 503, 500, auth, rate-limit, compaction, reply failure"
```

---

## Verification Checklist

After all three tasks:

- [ ] `python3 -m pytest --tb=short -q` — green, ≥ 256 tests
- [ ] `tests/test_logging_config.py` — 5 tests passing
- [ ] `tests/test_integration.py` — 14 tests passing (6 happy-path + 8 failure-path)
- [ ] `src/kore/logging_config.py` exists with `JsonFormatter` and `configure_logging()`
- [ ] `src/kore/main.py` no longer calls `logging.basicConfig()` directly
- [ ] No regressions in any previously-passing tests
