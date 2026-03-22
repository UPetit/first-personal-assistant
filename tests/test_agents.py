from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel
from pydantic_ai.models.test import TestModel

from kore.agents.base import BaseAgent, _extract_tool_calls
from kore.llm.types import AgentResponse, KoreMessage, ToolCall


# --- KoreDeps ---

def test_kdeps_config_only(sample_config):
    """KoreDeps can be created with only config; optional fields default to None."""
    from kore.agents.deps import KoreDeps
    deps = KoreDeps(config=sample_config)
    assert deps.config is sample_config
    assert deps.core_memory is None
    assert deps.event_log is None
    assert deps.retriever is None


def test_mock_deps_fixture_uses_kore_deps(mock_deps, sample_config):
    """mock_deps.deps is a real KoreDeps instance (not a SimpleNamespace)."""
    from kore.agents.deps import KoreDeps
    assert isinstance(mock_deps.deps, KoreDeps)
    assert mock_deps.deps.config is sample_config


# --- Construction ---

def test_base_agent_creation():
    model = TestModel()
    agent = BaseAgent(model, "test:model", "You are a test agent")
    assert agent is not None


def test_tool_registration():
    async def dummy_tool(ctx, x: str) -> str:
        """A dummy tool."""
        return x

    model = TestModel()
    agent = BaseAgent(model, "test:model", "test", tools=[dummy_tool])
    # pydantic-ai stores function tools in Agent._function_toolset.tools (dict keyed by name)
    tool_names = list(agent._agent._function_toolset.tools.keys())
    assert "dummy_tool" in tool_names


# --- run() ---

@pytest.mark.asyncio
async def test_run_returns_agent_response(mock_deps):
    model = TestModel()
    agent = BaseAgent(model, "test:model", "You are a test agent")
    result = await agent.run("Hello", deps=mock_deps)
    assert isinstance(result, AgentResponse)
    assert result.content       # non-empty
    assert result.model_used == "test:model"


@pytest.mark.asyncio
async def test_structured_output(mock_deps):
    """result_type=SomeModel → AgentResponse.content is valid JSON for that model.

    run() uses result.output.model_dump_json() when result.output is a Pydantic model,
    so content is a JSON string — NOT str(model) which gives Pydantic repr.
    """

    class Greeting(BaseModel):
        message: str

    model = TestModel()
    agent = BaseAgent(model, "test:model", "test", output_type=Greeting)
    result = await agent.run("say hello", deps=mock_deps)
    parsed = json.loads(result.content)   # must be valid JSON
    assert "message" in parsed


@pytest.mark.asyncio
async def test_run_with_message_history(mock_deps):
    """Non-empty message_history is accepted and forwarded without error."""
    model = TestModel()
    agent = BaseAgent(model, "test:model", "test")
    history = [
        KoreMessage(role="user", content="Previous question", timestamp=datetime.now(timezone.utc)),
        KoreMessage(role="assistant", content="Previous answer", timestamp=datetime.now(timezone.utc)),
    ]
    result = await agent.run("Follow-up", deps=mock_deps, message_history=history)
    assert isinstance(result, AgentResponse)
    assert result.content


# --- _extract_tool_calls (unit test of the helper) ---

def test_tool_call_captured():
    """_extract_tool_calls correlates ToolCallPart with ToolReturnPart by tool_call_id."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="my_tool",
                    args={"x": "hello"},
                    tool_call_id="call-1",
                )
            ],
            model_name="test:model",
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="my_tool",
                    content="echo: hello",
                    tool_call_id="call-1",
                )
            ]
        ),
    ]

    tool_calls = _extract_tool_calls(messages)

    assert len(tool_calls) == 1
    assert tool_calls[0].name == "my_tool"
    assert tool_calls[0].args == {"x": "hello"}
    assert tool_calls[0].result == "echo: hello"
    assert tool_calls[0].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_structured_output_output_field(mock_deps):
    """output_type=SomeModel → AgentResponse.output holds the typed model instance."""
    class Greeting(BaseModel):
        message: str

    model = TestModel()
    agent = BaseAgent(model, "test:model", "test", output_type=Greeting)
    result = await agent.run("say hello", deps=mock_deps)
    assert result.output is not None
    assert isinstance(result.output, Greeting)
    assert result.output.message is not None


@pytest.mark.asyncio
async def test_no_output_type_output_is_none(mock_deps):
    """When no output_type set, AgentResponse.output is None."""
    model = TestModel()
    agent = BaseAgent(model, "test:model", "test")
    result = await agent.run("hello", deps=mock_deps)
    assert result.output is None


# --- UsageLimits and error handling ---

def test_max_tool_calls_stored():
    """max_tool_calls parameter is accepted and stored on the agent."""
    model = TestModel()
    agent = BaseAgent(model, "test:model", "test", max_tool_calls=15)
    assert agent._max_tool_calls == 15


def test_max_tool_calls_defaults_to_none():
    """max_tool_calls defaults to None (no limit enforced)."""
    model = TestModel()
    agent = BaseAgent(model, "test:model", "test")
    assert agent._max_tool_calls is None


@pytest.mark.asyncio
async def test_unexpected_model_behavior_propagates(mock_deps):
    """UnexpectedModelBehavior raised inside run() must propagate to the caller."""
    from unittest.mock import AsyncMock, patch

    from pydantic_ai.exceptions import UnexpectedModelBehavior

    model = TestModel()
    agent = BaseAgent(model, "test:model", "test")
    with patch.object(
        agent._agent,
        "run",
        new=AsyncMock(side_effect=UnexpectedModelBehavior("bad response")),
    ):
        with pytest.raises(UnexpectedModelBehavior):
            await agent.run("hello", deps=mock_deps)


@pytest.mark.asyncio
async def test_usage_limit_exceeded_propagates(mock_deps):
    """UsageLimitExceeded raised inside run() must propagate to the caller."""
    from unittest.mock import AsyncMock, patch

    from pydantic_ai.exceptions import UsageLimitExceeded

    model = TestModel()
    agent = BaseAgent(model, "test:model", "test", max_tool_calls=1)
    with patch.object(
        agent._agent,
        "run",
        new=AsyncMock(side_effect=UsageLimitExceeded("tool calls limit reached")),
    ):
        with pytest.raises(UsageLimitExceeded):
            await agent.run("hello", deps=mock_deps)
