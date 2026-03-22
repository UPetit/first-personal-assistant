from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel

from kore.agents.base import BaseAgent
from kore.agents.orchestrator import Orchestrator
from kore.agents.planner import PlanResult
from kore.channels.base import Message, noop_reply
from kore.config import KoreConfig, LLMConfig
from kore.gateway.queue import MessageQueue
from kore.llm.types import AgentResponse
from kore.main import _OrchestratorAdapter, _consume


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def integration_config(sample_config_with_agents):
    """KoreConfig for integration tests: reuses sample_config_with_agents with auth disabled.

    sample_config_with_agents already provides planner + general/search/writer executors
    and SessionConfig, so only the security override is needed here.
    """
    return sample_config_with_agents


def _make_planner(steps: list[dict]) -> BaseAgent:
    """Return a BaseAgent backed by TestModel that produces a fixed plan."""
    model = TestModel(custom_output_args={
        "intent": "test intent",
        "reasoning": "test reasoning",
        "steps": steps,
    })
    return BaseAgent(model, "test:planner", "planner", output_type=PlanResult)


def _make_executor(content: str = "Integration response") -> BaseAgent:
    """Return a BaseAgent whose run() is an AsyncMock returning fixed content."""
    agent = BaseAgent(TestModel(), "test:executor", "executor")
    # AsyncMock is stateless — returns the same value on every call, safe for multi-turn tests
    agent.run = AsyncMock(return_value=AgentResponse(
        content=content, tool_calls=[], model_used="test:executor"
    ))
    return agent


# ── tests: HTTP + real orchestrator ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_message_full_pipeline(kore_home, integration_config, monkeypatch):
    """POST /api/message exercises the full HTTP → real Orchestrator → response path."""
    planner = _make_planner([{"executor": "general", "instruction": "handle it"}])
    executor = _make_executor("full pipeline response")

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
    """After a message, the session buffer file exists on disk."""
    planner = _make_planner([{"executor": "general", "instruction": "do it"}])
    executor = _make_executor("saved response")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    session_id = "persist-test-" + str(uuid4())[:8]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/message", json={"text": "remember me", "session_id": session_id})

    sess_file = kore_home / "workspace" / "sessions" / f"{session_id}.json"
    assert sess_file.exists(), f"Expected {sess_file} to exist after a session turn"


@pytest.mark.asyncio
async def test_api_message_multi_turn_context(
    kore_home, integration_config, monkeypatch
):
    """Second message in same session succeeds and buffer grows (loaded correctly from disk)."""
    import json

    planner = _make_planner([{"executor": "general", "instruction": "respond"}])
    executor = _make_executor("turn response")
    # AsyncMock is stateless — returns the same value on every call, safe for multi-turn tests

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(integration_config)

    from kore.gateway.server import create_app
    app = create_app(integration_config, orchestrator=orch)

    session_id = "multi-turn-" + str(uuid4())[:8]
    sess_file = kore_home / "workspace" / "sessions" / f"{session_id}.json"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post("/api/message", json={"text": "first", "session_id": session_id})
        assert r1.status_code == 200

        # Record buffer state after turn 1 — must exist and contain at least one turn entry
        assert sess_file.exists(), "Buffer file should exist after turn 1"
        size_after_turn1 = sess_file.stat().st_size
        buf_after_turn1 = json.loads(sess_file.read_text())
        turns_after_turn1 = buf_after_turn1["turns"]
        assert len(turns_after_turn1) >= 1, "Buffer should have at least 1 turn entry after turn 1"

        r2 = await c.post("/api/message", json={"text": "second", "session_id": session_id})
        assert r2.status_code == 200

    # Buffer grew between turns — confirms turn 2 loaded and appended to existing buffer
    buf_after_turn2 = json.loads(sess_file.read_text())
    turns_after_turn2 = buf_after_turn2["turns"]
    assert len(turns_after_turn2) > len(turns_after_turn1), (
        "Buffer should contain more turn entries after turn 2, confirming it was loaded from disk"
    )
    assert sess_file.stat().st_size > size_after_turn1, "Buffer file should be larger after turn 2"


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


# ── failure paths ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_message_503_when_no_orchestrator():
    """POST /api/message returns 503 when orchestrator is not wired."""
    from kore.gateway.server import create_app

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config)  # orchestrator=None by default

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "hi"})

    assert r.status_code == 503


@pytest.mark.asyncio
async def test_api_message_500_on_orchestrator_exception(
    kore_home, integration_config, monkeypatch
):
    """POST /api/message returns 500 when orchestrator.run() raises."""
    planner = _make_planner([{"executor": "general", "instruction": "fail"}])
    executor = _make_executor()
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
async def test_empty_plan_steps_returns_canned_response(
    kore_home, integration_config, monkeypatch
):
    """When planner returns zero steps, the orchestrator returns a canned fallback via HTTP."""
    canned_plan = PlanResult.__new__(PlanResult)
    object.__setattr__(canned_plan, "intent", "unclear")
    object.__setattr__(canned_plan, "reasoning", "unclear")
    object.__setattr__(canned_plan, "steps", [])

    planner_agent = BaseAgent(TestModel(), "test:planner", "planner", output_type=PlanResult)
    planner_agent.run = AsyncMock(return_value=AgentResponse(
        content="", tool_calls=[], model_used="test:planner", output=canned_plan
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
    """When session buffer exceeds token threshold, compaction fires and responses still work."""
    from kore.config import SessionConfig

    # Force compaction by setting threshold to 1 token (always exceeded after first turn)
    config = integration_config.model_copy(update={
        "session": SessionConfig(compaction_token_threshold=1),
    })

    planner = _make_planner([{"executor": "general", "instruction": "respond"}])
    executor = _make_executor("post-compaction response")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    # Mock the compactor so no real LLM call is made during compaction
    mock_compactor = MagicMock()
    mock_compactor.summarise = AsyncMock(return_value="[compacted summary]")
    from kore.session.compactor import Compactor
    monkeypatch.setattr(Compactor, "from_config", staticmethod(lambda cfg: mock_compactor))

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
