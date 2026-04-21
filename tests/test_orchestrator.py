from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import models

from kore.agents.orchestrator import Orchestrator
from kore.config import KoreConfig, PrimaryAgentConfig

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def new_schema_config(sample_config, tmp_path):
    from kore.config import AgentsConfig
    cfg = sample_config.model_copy(update={
        "agents": AgentsConfig(
            primary=PrimaryAgentConfig(
                model="anthropic:claude-sonnet-4-6",
                prompt="prompts/primary.md",
                tools=[],
            ),
            subagents={},
        )
    })
    return cfg


@pytest.mark.asyncio
async def test_orchestrator_run_emits_span_shaped_trace(new_schema_config, kore_home):
    trace_store = MagicMock()
    trace_store.add = AsyncMock()

    orchestrator = Orchestrator(new_schema_config, trace_store=trace_store)

    from pydantic_ai.models.test import TestModel
    orchestrator._primary.model = TestModel(custom_output_text="hi back")  # type: ignore[attr-defined]

    resp = await orchestrator.run("hi there", session_id="s1")

    assert resp.content
    types_emitted = [call.args[0]["type"] for call in trace_store.add.call_args_list]
    assert types_emitted[0] == "session_start"
    assert "primary_start" in types_emitted
    assert "primary_done" in types_emitted
    assert types_emitted[-1] == "session_done"

    for call in trace_store.add.call_args_list[1:]:
        ev = call.args[0]
        if ev["type"] != "session_error":
            assert ev.get("parent_span_id") is not None


@pytest.mark.asyncio
async def test_orchestrator_prepends_core_memory_not_events(new_schema_config, kore_home):
    core_mem = MagicMock()
    core_mem.format_for_prompt = MagicMock(return_value="name=Alice")

    retriever = MagicMock()
    retriever.search = AsyncMock()

    orchestrator = Orchestrator(
        new_schema_config, core_memory=core_mem, retriever=retriever
    )
    from pydantic_ai.models.test import TestModel
    orchestrator._primary.model = TestModel(custom_output_text="ok")  # type: ignore[attr-defined]

    await orchestrator.run("hi", session_id="s2")

    retriever.search.assert_not_called()
    core_mem.format_for_prompt.assert_called()


@pytest.mark.asyncio
async def test_orchestrator_emits_session_error_on_exception(new_schema_config, monkeypatch, kore_home):
    trace_store = MagicMock()
    trace_store.add = AsyncMock()

    orchestrator = Orchestrator(new_schema_config, trace_store=trace_store)

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(orchestrator._primary, "run", boom)

    with pytest.raises(RuntimeError):
        await orchestrator.run("anything", session_id="s3")

    types_emitted = [c.args[0]["type"] for c in trace_store.add.call_args_list]
    assert "session_error" in types_emitted


@pytest.mark.asyncio
async def test_orchestrator_graceful_on_usage_limit_exceeded(new_schema_config, monkeypatch, kore_home):
    from pydantic_ai.exceptions import UsageLimitExceeded
    trace_store = MagicMock()
    trace_store.add = AsyncMock()

    orchestrator = Orchestrator(new_schema_config, trace_store=trace_store)

    async def cap(*args, **kwargs):
        raise UsageLimitExceeded("request_limit=30 hit")

    monkeypatch.setattr(orchestrator._primary, "run", cap)

    resp = await orchestrator.run("x", session_id="s4")
    assert resp.content
    types_emitted = [c.args[0]["type"] for c in trace_store.add.call_args_list]
    assert "session_error" in types_emitted
    assert "session_done" not in types_emitted


@pytest.mark.asyncio
async def test_extract_tool_calls_emits_subagent_spans():
    from kore.agents.orchestrator import _extract_tool_calls_with_spans
    from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

    emitted: list[dict] = []

    async def emit(ev):
        emitted.append(ev)

    call_part = ToolCallPart(tool_name="deep_research", args={"query": "x"}, tool_call_id="c1")
    return_part = ToolReturnPart(tool_name="deep_research", content="result-preview", tool_call_id="c1")
    messages = [
        ModelResponse(parts=[call_part], model_name="test"),
        ModelRequest(parts=[return_part]),
    ]

    result = await _extract_tool_calls_with_spans(
        messages,
        session_id="s",
        parent_span_id="p",
        emit=emit,
        subagent_names={"deep_research"},
    )
    types = [e["type"] for e in emitted]
    assert "tool_call" in types
    assert "subagent_start" in types
    assert "subagent_done" in types
    assert "tool_result" in types
    # subagent_start appears after tool_call
    assert types.index("subagent_start") > types.index("tool_call")
    # subagent_done appears before tool_result
    assert types.index("subagent_done") < types.index("tool_result")
    assert len(result) == 1 and result[0].name == "deep_research"
