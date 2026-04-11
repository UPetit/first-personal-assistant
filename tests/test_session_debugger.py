from __future__ import annotations

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
async def test_orchestrator_emits_events_in_correct_order(kore_home, tmp_path):
    """With trace_store wired in, run() persists session_start → plan_result →
    executor_start → executor_done → session_done in the right order."""
    from kore.gateway.trace_store import TraceStore
    from kore.agents.orchestrator import Orchestrator

    config = _make_config()
    store = TraceStore(tmp_path / "kore.db")

    plan_response = MagicMock()
    plan_response.output = _make_plan_result()
    exec_response = _make_agent_response("hello")

    orch = Orchestrator(config, trace_store=store)
    with (
        patch.object(orch._planner, "run", new=AsyncMock(return_value=plan_response)),
        patch.object(orch, "_get_executor") as mock_get_exec,
    ):
        mock_exec = MagicMock()
        mock_exec.run = AsyncMock(return_value=exec_response)
        mock_exec.skills_loaded = []
        mock_get_exec.return_value = mock_exec

        await orch.run("hello", "test_session")

    events = await store.get_session("test_session")
    types = [e["type"] for e in events]
    assert types == [
        "session_start",
        "plan_summary",
        "plan_result",
        "executor_start",
        "executor_done",
        "session_done",
    ]
    assert events[0]["message"] == "hello"
    assert events[1]["intent"] == "test intent"
    assert events[1]["reasoning"] == "test reasoning"
    assert events[2]["step_index"] == 0
    assert events[2]["executor"] == "general"
    assert events[2]["reasoning"] == "test reasoning"
    assert events[3]["step_index"] == 0
    assert events[3]["executor_name"] == "general"
    assert events[4]["step_index"] == 0
    assert events[5]["response"] == "hello"


@pytest.mark.asyncio
async def test_orchestrator_emits_tool_call_and_result_events(kore_home, tmp_path):
    """When executor has tool_calls, tool_call and tool_result events are persisted."""
    from kore.gateway.trace_store import TraceStore
    from kore.agents.orchestrator import Orchestrator
    from kore.llm.types import ToolCall

    config = _make_config()
    store = TraceStore(tmp_path / "kore.db")

    tc = ToolCall(tool_call_id="tc1", name="web_search", args={"query": "test"}, result="results")
    plan_response = MagicMock()
    plan_response.output = _make_plan_result()
    exec_response = _make_agent_response("done", tool_calls=[tc])

    orch = Orchestrator(config, trace_store=store)
    with (
        patch.object(orch._planner, "run", new=AsyncMock(return_value=plan_response)),
        patch.object(orch, "_get_executor") as mock_get_exec,
    ):
        mock_exec = MagicMock()
        mock_exec.run = AsyncMock(return_value=exec_response)
        mock_exec.skills_loaded = []
        mock_get_exec.return_value = mock_exec

        await orch.run("search this", "test_session")

    events = await store.get_session("test_session")
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
async def test_orchestrator_without_trace_store_emits_nothing(kore_home):
    """Orchestrator with trace_store=None must not raise AttributeError."""
    from kore.agents.orchestrator import Orchestrator

    config = _make_config()
    plan_response = MagicMock()
    plan_response.output = _make_plan_result()
    exec_response = _make_agent_response("done")

    orch = Orchestrator(config)  # no trace_store
    with (
        patch.object(orch._planner, "run", new=AsyncMock(return_value=plan_response)),
        patch.object(orch, "_get_executor") as mock_get_exec,
    ):
        mock_exec = MagicMock()
        mock_exec.run = AsyncMock(return_value=exec_response)
        mock_exec.skills_loaded = []
        mock_get_exec.return_value = mock_exec

        # Must not raise
        result = await orch.run("hi", "test_session")
    assert result.content == "done"


# ── REST /api/sessions/{id}/trace ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_trace_returns_empty_when_store_is_none(kore_home):
    """GET /api/sessions/{id}/trace returns [] when trace_store is None."""
    from httpx import ASGITransport, AsyncClient
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config)  # no trace_store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/any_session/trace")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_session_trace_returns_persisted_events(kore_home, tmp_path):
    """GET /api/sessions/{id}/trace returns all events for the session."""
    from httpx import ASGITransport, AsyncClient
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    await store.add({"type": "session_start", "session_id": "s1", "ts": "t"})
    await store.add({"type": "session_done", "session_id": "s1", "ts": "t"})
    await store.add({"type": "session_start", "session_id": "s2", "ts": "t"})

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config, trace_store=store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/s1/trace")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["type"] == "session_start"
    assert data[1]["type"] == "session_done"


# ── Wiring ──────────────────────────────────────────────────────────────────


def test_create_app_with_trace_store_none_stores_none_in_state():
    """create_app(config) must set app.state.trace_store to None by default."""
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config)
    assert app.state.trace_store is None


def test_create_app_with_trace_store_stores_instance(tmp_path):
    """create_app(config, trace_store=store) must store the instance in app.state."""
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app
    from kore.gateway.trace_store import TraceStore

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    store = TraceStore(tmp_path / "kore.db")
    app = create_app(config, trace_store=store)
    assert app.state.trace_store is store
