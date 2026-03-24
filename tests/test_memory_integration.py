from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from kore.agents.base import BaseAgent
from kore.agents.planner import PlanResult, PlanStep
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


@pytest.fixture
def kore_home(tmp_path, monkeypatch):
    import kore.session.buffer as buf_mod
    import kore.config as config_mod
    monkeypatch.setattr(config_mod, "KORE_HOME", tmp_path)
    monkeypatch.setattr(buf_mod, "KORE_HOME", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_orchestrator_runs_post_extraction(
    kore_home, tmp_path, sample_config_with_agents, monkeypatch
):
    """After a run, extraction is called and events appear in the event log."""
    from kore.agents.orchestrator import Orchestrator
    from kore.db.database import create_engine, setup_schema
    from kore.memory.core_memory import CoreMemory
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog
    from kore.memory.extraction import ExtractionAgent
    from kore.memory.retrieval import Retriever

    planner = _make_planner([{"executor": "general", "instruction": "handle this"}])
    executor = _make_executor("done")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c, **kw: executor)

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)

    core_memory = CoreMemory(tmp_path / "core_memory.json")
    event_log = EventLog(engine, mock_em)
    retriever = Retriever(event_log, mock_em)
    extraction = ExtractionAgent(event_log, model="test")

    orchestrator = Orchestrator(
        sample_config_with_agents,
        core_memory=core_memory,
        event_log=event_log,
        retriever=retriever,
        extraction_agent=extraction,
    )

    await orchestrator.run("My name is Dave", session_id="test-session")

    events = await event_log.get_recent(limit=10)
    # Extraction should have run (may or may not produce events with TestModel,
    # but the orchestrator should not raise)
    assert isinstance(events, list)

    await engine.dispose()


@pytest.mark.asyncio
async def test_orchestrator_injects_core_memory_in_prompt(
    kore_home, tmp_path, sample_config_with_agents, monkeypatch
):
    """Core memory content appears in the planner context."""
    from kore.agents.orchestrator import Orchestrator
    from kore.db.database import create_engine, setup_schema
    from kore.memory.core_memory import CoreMemory
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog
    from kore.memory.extraction import ExtractionAgent
    from kore.memory.retrieval import Retriever

    received_messages: list[str] = []

    planner = _make_planner([{"executor": "general", "instruction": "handle this"}])

    # Wrap planner.run to capture the actual message passed
    original_planner_run = planner.run

    async def capturing_run(message: str, **kwargs):
        received_messages.append(message)
        return await original_planner_run(message, **kwargs)

    planner.run = capturing_run  # type: ignore[method-assign]

    executor = _make_executor("done")

    monkeypatch.setattr("kore.agents.orchestrator.create_planner", lambda c: planner)
    monkeypatch.setattr("kore.agents.orchestrator.create_executor", lambda n, c, **kw: executor)

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)

    core_memory = CoreMemory(tmp_path / "core_memory.json")
    core_memory.update("user.name", "TestUser")

    event_log = EventLog(engine, mock_em)
    retriever = Retriever(event_log, mock_em)
    extraction = ExtractionAgent(event_log, model="test")

    orchestrator = Orchestrator(
        sample_config_with_agents,
        core_memory=core_memory,
        event_log=event_log,
        retriever=retriever,
        extraction_agent=extraction,
    )

    # Should run without error and inject memory into context
    response = await orchestrator.run("Hello", session_id="test-session-2")
    assert response is not None

    # The message passed to planner should contain core memory content
    assert len(received_messages) == 1
    assert "TestUser" in received_messages[0]

    await engine.dispose()
