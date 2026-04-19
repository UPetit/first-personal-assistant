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
