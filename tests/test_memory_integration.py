from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from kore.agents.orchestrator import Orchestrator
from kore.config import AgentsConfig, PrimaryAgentConfig

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def new_schema_config(sample_config):
    return sample_config.model_copy(update={
        "agents": AgentsConfig(
            primary=PrimaryAgentConfig(
                model="anthropic:claude-sonnet-4-6",
                prompt="prompts/primary.md",
                tools=[],
            ),
            subagents={},
        )
    })


@pytest.mark.asyncio
async def test_orchestrator_invokes_post_extraction(new_schema_config, kore_home):
    """Orchestrator calls extraction_agent.extract_and_store with buffer history after primary completes."""
    extraction = MagicMock()
    extraction.extract_and_store = AsyncMock()

    orchestrator = Orchestrator(new_schema_config, extraction_agent=extraction)
    orchestrator._primary.model = TestModel(custom_output_text="reply")  # type: ignore[attr-defined]

    await orchestrator.run("hi", session_id="sess-extract")

    extraction.extract_and_store.assert_awaited_once()
    history = extraction.extract_and_store.await_args.args[0]
    roles = [m.role for m in history]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_orchestrator_swallows_extraction_errors(new_schema_config, kore_home):
    """A failing extraction must not break the turn — it's best-effort."""
    extraction = MagicMock()
    extraction.extract_and_store = AsyncMock(side_effect=RuntimeError("boom"))

    orchestrator = Orchestrator(new_schema_config, extraction_agent=extraction)
    orchestrator._primary.model = TestModel(custom_output_text="reply")  # type: ignore[attr-defined]

    resp = await orchestrator.run("hi", session_id="sess-extract-err")
    assert resp.content == "reply"
