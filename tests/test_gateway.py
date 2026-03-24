from __future__ import annotations

import asyncio
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock

from kore.config import KoreConfig


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_config() -> KoreConfig:
    from kore.config import LLMConfig
    return KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
    )


def _make_app(config: KoreConfig | None = None, **kwargs):
    from kore.gateway.server import create_app
    return create_app(config or _make_config(), **kwargs)


# ── MessageQueue ──────────────────────────────────────────────────────────────

def test_message_queue_maxsize():
    """MessageQueue(maxsize=N) sets the underlying asyncio.Queue's maxsize."""
    from kore.gateway.queue import MessageQueue
    queue = MessageQueue(maxsize=10)
    assert queue._q.maxsize == 10


def test_message_queue_default_is_unbounded():
    """MessageQueue() created without maxsize defaults to unbounded (maxsize=0)."""
    from kore.gateway.queue import MessageQueue
    queue = MessageQueue()
    assert queue._q.maxsize == 0


# ── log_handler ───────────────────────────────────────────────────────────────

def test_log_handler_emit_buffers_message():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello world", (), None)
    handler.emit(record)
    assert any("hello world" in entry for entry in handler.recent(10))


def test_log_handler_listener_receives_emitted_message():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    q = handler.add_listener()
    record = logging.LogRecord("test", logging.INFO, "", 0, "broadcast me", (), None)
    handler.emit(record)
    assert not q.empty()
    msg = q.get_nowait()
    assert "broadcast me" in msg


def test_log_handler_remove_listener_stops_delivery():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    q = handler.add_listener()
    handler.remove_listener(q)
    record = logging.LogRecord("test", logging.INFO, "", 0, "gone", (), None)
    handler.emit(record)
    assert q.empty()


def test_log_handler_recent_returns_last_n():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    for i in range(5):
        record = logging.LogRecord("t", logging.INFO, "", 0, f"msg {i}", (), None)
        handler.emit(record)
    recent = handler.recent(3)
    assert len(recent) == 3
    assert "msg 4" in recent[-1]


# ── REST routes ───────────────────────────────────────────────────────────────

def _make_app_with_components(**kwargs):
    """Build app with mock components pre-wired."""
    from kore.config import ExecutorConfig, AgentsConfig

    config = _make_config()
    # Give it a planner + general executor so /api/agents has something to return
    config = config.model_copy(update={"agents": AgentsConfig(
        planner=None,
        executors={
            "general": ExecutorConfig(
                model="anthropic:claude-sonnet-4-6",
                prompt_file="general.md",
                tools=["web_search"],
                description="General executor",
            )
        },
    )})

    core_memory = MagicMock()
    core_memory.get.return_value = {"user": {"name": "Alice"}}

    scheduler = MagicMock()
    scheduler.list_jobs.return_value = [
        {"id": "daily_digest", "next_run": "2026-03-18 08:00:00"}
    ]

    return _make_app(config, core_memory=core_memory, scheduler=scheduler, **kwargs)


@pytest.mark.asyncio
async def test_get_jobs_returns_list():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/jobs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["id"] == "daily_digest"


@pytest.mark.asyncio
async def test_post_job_creates_job():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/jobs", json={
            "job_id": "new_job",
            "schedule": "0 9 * * *",
            "prompt": "Do the thing",
        })
    assert r.status_code == 201
    app.state.scheduler.add_job.assert_called_once_with(
        "new_job", "0 9 * * *", "Do the thing", source="ui", executor="general", timezone=None,
    )


@pytest.mark.asyncio
async def test_delete_job_removes_it():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/jobs/daily_digest")
    assert r.status_code == 200
    app.state.scheduler.remove_job.assert_called_once_with("daily_digest")


@pytest.mark.asyncio
async def test_get_agents_returns_executor_list():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    assert "general" in data["executors"]
    assert data["executors"]["general"]["model"] == "anthropic:claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_get_memory_returns_dict():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/memory")
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_put_memory_updates_path():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put("/api/memory", json={"path": "user.name", "value": "Bob"},
                        auth=("admin", "secret"))
    assert r.status_code == 200
    app.state.core_memory.update.assert_called_once_with("user.name", "Bob")


@pytest.mark.asyncio
async def test_delete_memory_path():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/memory/user.name")
    assert r.status_code == 200
    app.state.core_memory.delete.assert_called_once_with("user.name")


@pytest.mark.asyncio
async def test_get_logs_returns_recent_entries():
    import logging
    app = _make_app_with_components()
    # Emit a log so the handler buffer has something
    record = logging.LogRecord("kore", logging.INFO, "", 0, "startup complete", (), None)
    app.state.log_handler.emit(record)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=10")
    assert r.status_code == 200
    entries = r.json()
    assert isinstance(entries, list)
    assert any("startup complete" in e for e in entries)


@pytest.mark.asyncio
async def test_post_message_calls_orchestrator():
    from unittest.mock import AsyncMock
    from kore.llm.types import AgentResponse

    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=AgentResponse(
        content="Hello back!", tool_calls=[], model_used="test"
    ))
    app = _make_app_with_components(orchestrator=mock_orch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "Hello", "session_id": "api_test"},
                         auth=("admin", "secret"))
    assert r.status_code == 200
    assert r.json()["response"] == "Hello back!"
    mock_orch.run.assert_called_once_with("Hello", "api_test")


@pytest.mark.asyncio
async def test_post_message_503_when_no_orchestrator():
    app = _make_app_with_components(orchestrator=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "Hi"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_post_job_503_when_no_scheduler():
    app = _make_app(_make_config())  # no scheduler
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/jobs", json={
            "job_id": "x", "schedule": "0 * * * *", "prompt": "hi"
        })
    assert r.status_code == 503


# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_ws_logs_accepts_connection():
    """TestClient (sync) supports WebSocket testing via starlette."""
    from starlette.testclient import TestClient
    app = _make_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/logs") as ws:
        # connection accepted — no exception means success
        pass


def test_ws_logs_receives_emitted_log():
    """Log emitted after connect is delivered to the WebSocket client."""
    import logging
    import time
    from starlette.testclient import TestClient
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with client.websocket_connect("/ws/logs") as ws:
        # Give the WebSocket handler a moment to reach the await queue.get() call
        time.sleep(0.05)
        record = logging.LogRecord("kore", logging.INFO, "", 0, "ws test log", (), None)
        app.state.log_handler.emit(record)
        data = ws.receive_text()
    assert "ws test log" in data


def test_ws_logs_disconnect_removes_listener():
    """After disconnect, the listener queue is removed from the handler."""
    import time
    from starlette.testclient import TestClient
    app = _make_app()
    client = TestClient(app)
    before = len(app.state.log_handler._listeners)
    with client.websocket_connect("/ws/logs"):
        time.sleep(0.05)  # let handler reach await queue.get()
        during = len(app.state.log_handler._listeners)
    # Allow a moment for the finally block to execute
    time.sleep(0.05)
    after = len(app.state.log_handler._listeners)
    assert during == before + 1
    assert after == before


# ── Telegram webhook ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telegram_webhook_calls_process_update():
    from unittest.mock import AsyncMock, MagicMock

    mock_channel = MagicMock()
    mock_channel.process_update = AsyncMock()

    app = _make_app(telegram_channel=mock_channel)
    payload = {"update_id": 1, "message": {"text": "hello"}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/telegram/webhook", json=payload)
    assert r.status_code == 200
    mock_channel.process_update.assert_called_once_with(payload)


@pytest.mark.asyncio
async def test_telegram_webhook_503_without_channel():
    app = _make_app()  # no telegram_channel
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 503


# ── main.py integration ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_app_with_orchestrator_state():
    """Verify orchestrator is accessible from app.state after create_app."""
    from unittest.mock import MagicMock
    mock_orch = MagicMock()
    app = _make_app(orchestrator=mock_orch)
    assert app.state.orchestrator is mock_orch


def test_create_app_stores_skill_registry_in_state():
    """skill_registry passed to create_app() is accessible via app.state."""
    from unittest.mock import MagicMock
    registry = MagicMock()
    app = _make_app(skill_registry=registry)
    assert app.state.skill_registry is registry


def test_create_app_skill_registry_defaults_to_none():
    """create_app() without skill_registry sets app.state.skill_registry to None."""
    app = _make_app()
    assert app.state.skill_registry is None


# ── exception sanitization ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_message_exception_returns_sanitized_500():
    """POST /api/message exception must not leak the raw error message."""
    from unittest.mock import AsyncMock

    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(side_effect=RuntimeError("internal secret path: /etc/kore/keys"))

    app = _make_app(_make_config(), orchestrator=mock_orch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "hi"})

    assert r.status_code == 500
    body = r.json()
    assert "detail" in body["detail"]
    assert "request_id" in body["detail"]
    assert "secret" not in r.text
    assert "internal" not in r.text


@pytest.mark.asyncio
async def test_put_memory_exception_returns_sanitized_500():
    """PUT /api/memory exception must return 500 with request_id, not raw error."""
    core_memory = MagicMock()
    core_memory.update.side_effect = RuntimeError("db path leaked: /home/user/.kore/kore.db")

    app = _make_app(_make_config(), core_memory=core_memory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(
            "/api/memory",
            json={"path": "user.name", "value": "Bob"},
            auth=("admin", "secret"),
        )

    assert r.status_code == 500
    body = r.json()
    assert "detail" in body["detail"]
    assert "request_id" in body["detail"]
    assert "db path" not in r.text


@pytest.mark.asyncio
async def test_delete_memory_exception_returns_sanitized_500():
    """DELETE /api/memory exception must return 500 with request_id, not raw error."""
    core_memory = MagicMock()
    core_memory.delete.side_effect = KeyError("secret_key")

    app = _make_app(_make_config(), core_memory=core_memory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/memory/user.name")

    assert r.status_code == 500
    body = r.json()
    assert "detail" in body["detail"]
    assert "request_id" in body["detail"]
    assert "secret_key" not in r.text


# ── /api/logs query param bounds ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_logs_n_zero_returns_422():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=0")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_logs_n_too_large_returns_422():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=1001")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_logs_valid_n_returns_200():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=50")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
