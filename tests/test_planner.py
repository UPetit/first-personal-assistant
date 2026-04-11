from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from kore.agents.base import BaseAgent
from kore.agents.planner import PlanResult, PlanStep, _build_executors_summary


def test_plan_step_model():
    step = PlanStep(executor="search", instruction="find info about Python")
    assert step.executor == "search"
    assert step.instruction == "find info about Python"


def test_plan_result_requires_steps():
    """PlanResult.steps has min_length=1 — empty list raises ValidationError."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PlanResult(intent="test", reasoning="test", steps=[])


def test_plan_result_valid():
    plan = PlanResult(
        intent="research Python",
        reasoning="user wants info",
        steps=[PlanStep(executor="search", instruction="search Python docs")],
    )
    assert plan.intent == "research Python"
    assert len(plan.steps) == 1


def test_build_executors_summary(sample_config_with_agents):
    summary = _build_executors_summary(sample_config_with_agents)
    assert "general" in summary
    assert "search" in summary
    assert "Web research" in summary


@pytest.mark.asyncio
async def test_planner_returns_plan_result(mock_deps):
    """BaseAgent with output_type=PlanResult returns PlanResult in data field."""
    model = TestModel(custom_output_args={
        "intent": "find information about Python",
        "reasoning": "user wants research",
        "steps": [{"executor": "search", "instruction": "search for Python info"}],
    })
    agent = BaseAgent(model, "test:model", "you are a planner", output_type=PlanResult)
    result = await agent.run("tell me about Python", deps=mock_deps)
    assert result.output is not None
    assert isinstance(result.output, PlanResult)
    assert result.output.intent == "find information about Python"
    assert len(result.output.steps) == 1
    assert result.output.steps[0].executor == "search"


@pytest.mark.asyncio
async def test_planner_single_step(mock_deps):
    """Single-step plan routes to the specified executor."""
    model = TestModel(custom_output_args={
        "intent": "search for info",
        "reasoning": "only search needed",
        "steps": [{"executor": "search", "instruction": "search for Python docs"}],
    })
    agent = BaseAgent(model, "test:model", "you are a planner", output_type=PlanResult)
    result = await agent.run("find Python docs", deps=mock_deps)
    assert result.output is not None
    assert len(result.output.steps) == 1
    assert result.output.steps[0].executor == "search"
    assert result.output.steps[0].instruction == "search for Python docs"


@pytest.mark.asyncio
async def test_planner_multi_step(mock_deps):
    """Multi-step plan preserves step order."""
    model = TestModel(custom_output_args={
        "intent": "research and summarize",
        "reasoning": "two steps needed",
        "steps": [
            {"executor": "search", "instruction": "find info"},
            {"executor": "general", "instruction": "summarize findings"},
        ],
    })
    agent = BaseAgent(model, "test:model", "you are a planner", output_type=PlanResult)
    result = await agent.run("research and summarize Python", deps=mock_deps)
    assert result.output is not None
    assert len(result.output.steps) == 2
    assert result.output.steps[0].executor == "search"
    assert result.output.steps[1].executor == "general"


def test_executor_list_in_prompt(sample_config_with_agents):
    """create_planner injects executor names into the system prompt via {{EXECUTORS}}."""
    # Inspect the built summary directly — avoids real LLM construction
    summary = _build_executors_summary(sample_config_with_agents)
    assert "general" in summary
    assert "search" in summary
    # Each description should appear
    assert "Handles complex" in summary
    assert "Web research" in summary
