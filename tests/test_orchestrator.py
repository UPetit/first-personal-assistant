from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai.models.test import TestModel

from kore.agents.base import BaseAgent
from kore.agents.orchestrator import Orchestrator
from kore.agents.planner import PlanResult, PlanStep
from kore.config import ConfigError
from kore.llm.types import AgentResponse


def _make_planner(steps: list[dict]) -> BaseAgent:
    model = TestModel(custom_output_args={
        "intent": "test intent",
        "reasoning": "test reasoning",
        "steps": steps,
    })
    return BaseAgent(model, "test:planner", "you are a planner", output_type=PlanResult)


def _make_executor(response_content: str = "executor result") -> BaseAgent:
    model = TestModel()
    agent = BaseAgent(model, "test:executor", "you are an executor")
    agent.run = AsyncMock(return_value=AgentResponse(
        content=response_content, tool_calls=[], model_used="test:executor"
    ))
    return agent


def test_planner_missing_raises(sample_config):
    """Orchestrator raises ConfigError when planner is absent from config."""
    with pytest.raises(ConfigError, match="Planner not configured"):
        Orchestrator(sample_config)


@pytest.mark.asyncio
async def test_full_pipeline(kore_home, sample_config_with_agents, monkeypatch):
    """Planner → executor → AgentResponse returned, session saved."""
    planner = _make_planner([{"executor": "general", "instruction": "do something"}])
    executor = _make_executor("final answer")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(sample_config_with_agents)
    session_id = str(uuid4())
    result = await orch.run("hello", session_id)

    assert isinstance(result, AgentResponse)
    assert result.content == "final answer"

    # Session file written to disk
    sess_file = kore_home / "workspace" / "sessions" / f"{session_id}.json"
    assert sess_file.exists()


@pytest.mark.asyncio
async def test_feed_forward_context(kore_home, sample_config_with_agents, monkeypatch):
    """Step 2's instruction includes step 1's output as context."""
    planner = _make_planner([
        {"executor": "search", "instruction": "find info"},
        {"executor": "writer", "instruction": "write summary"},
    ])

    received: list[str] = []

    async def recording_run(message: str, **kwargs: object) -> AgentResponse:
        received.append(message)
        return AgentResponse(content="step output", tool_calls=[], model_used="test")

    executor = BaseAgent(TestModel(), "test:executor", "executor")
    executor.run = recording_run  # type: ignore[method-assign]

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(sample_config_with_agents)
    await orch.run("research and write", str(uuid4()))

    assert len(received) == 2
    assert "step output" in received[1]  # step 1's output in step 2's context


@pytest.mark.asyncio
async def test_orchestrator_passes_kore_deps_to_executor(kore_home, sample_config_with_agents, monkeypatch):
    """Orchestrator must build a KoreDeps instance and pass it as deps= to executor.run()."""
    from kore.agents.deps import KoreDeps

    planner = _make_planner([{"executor": "general", "instruction": "do it"}])
    executor = _make_executor("result")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(sample_config_with_agents)
    await orch.run("test", str(uuid4()))

    call_kwargs = executor.run.call_args.kwargs
    assert "deps" in call_kwargs
    assert isinstance(call_kwargs["deps"], KoreDeps)


@pytest.mark.asyncio
async def test_unknown_executor_fallback(
    kore_home, sample_config_with_agents, monkeypatch, caplog
):
    """Unknown executor name falls back to 'general' with a warning logged."""
    planner = _make_planner([{"executor": "nonexistent", "instruction": "do it"}])
    executor = _make_executor("general fallback result")

    def fake_create_executor(name: str, config: object) -> BaseAgent:
        assert name == "general"   # must fall back to general
        return executor

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", fake_create_executor)

    orch = Orchestrator(sample_config_with_agents)
    with caplog.at_level(logging.WARNING):
        result = await orch.run("do something", str(uuid4()))

    assert result.content == "general fallback result"
    assert any("nonexistent" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_empty_plan_steps(kore_home, sample_config_with_agents, monkeypatch):
    """When plan has no steps (guard fires), a canned response is returned."""
    # steps=[] would fail PlanResult validation — guard handles post-retry failure.
    # Simulate by patching run() to return a response with data.steps = []
    canned_plan = PlanResult.__new__(PlanResult)
    object.__setattr__(canned_plan, "intent", "unclear")
    object.__setattr__(canned_plan, "reasoning", "unclear")
    object.__setattr__(canned_plan, "steps", [])

    planner_agent = BaseAgent(TestModel(), "test:planner", "planner", output_type=PlanResult)
    planner_agent.run = AsyncMock(return_value=AgentResponse(
        content="", tool_calls=[], model_used="test:planner", output=canned_plan
    ))

    executor_called = False

    async def should_not_call(*args: object, **kwargs: object) -> AgentResponse:
        nonlocal executor_called
        executor_called = True
        return AgentResponse(content="", tool_calls=[], model_used="test")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner_agent)

    orch = Orchestrator(sample_config_with_agents)
    result = await orch.run("unclear request", str(uuid4()))

    assert "rephrase" in result.content.lower()
    assert not executor_called


@pytest.mark.asyncio
async def test_executors_receive_no_history(
    kore_home, sample_config_with_agents, monkeypatch
):
    """Executor run() is called without message_history."""
    planner = _make_planner([{"executor": "general", "instruction": "do something"}])

    run_kwargs: dict = {}

    async def recording_run(message: str, **kwargs: object) -> AgentResponse:
        run_kwargs.update(kwargs)
        return AgentResponse(content="done", tool_calls=[], model_used="test")

    executor = BaseAgent(TestModel(), "test:executor", "executor")
    executor.run = recording_run  # type: ignore[method-assign]

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c: executor)

    orch = Orchestrator(sample_config_with_agents)
    await orch.run("do something", str(uuid4()))

    assert "message_history" not in run_kwargs
