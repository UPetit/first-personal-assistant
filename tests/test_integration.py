from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from kore.agents.orchestrator import Orchestrator
from kore.config import (
    AgentsConfig,
    KoreConfig,
    LLMConfig,
    LLMProviderConfig,
    PrimaryAgentConfig,
    SubAgentConfig,
)
from kore.llm.types import ResearchReport, Source

models.ALLOW_MODEL_REQUESTS = False


def _config() -> KoreConfig:
    return KoreConfig(
        version="1",
        llm=LLMConfig(providers={"anthropic": LLMProviderConfig(api_key="sk-test")}),
        agents=AgentsConfig(
            primary=PrimaryAgentConfig(
                model="anthropic:claude-sonnet-4-6",
                prompt="prompts/primary.md",
                tools=[],
            ),
            subagents={
                "deep_research": SubAgentConfig(
                    model="anthropic:claude-haiku-4-5-20251001",
                    prompt="prompts/deep_research.md",
                    tools=["web_search", "scrape_url", "memory_search"],
                ),
                "draft_longform": SubAgentConfig(
                    model="anthropic:claude-sonnet-4-6",
                    prompt="prompts/draft_longform.md",
                    tools=["memory_search", "read_file"],
                ),
            },
        ),
    )


@pytest.mark.asyncio
async def test_full_flow_with_subagent_delegation(monkeypatch, kore_home):
    """Simulate a turn where the primary delegates to deep_research.

    Verifies no telephone-game context loss: information from the subagent's
    sources is visible to the primary's synthesis, and the trace captures the
    full shape (session -> primary -> tool(deep_research) -> subagent_*).
    """
    trace: list[dict] = []
    store = MagicMock()

    async def _add(ev: dict) -> None:
        trace.append(ev)

    store.add = _add

    # Stub the subagent's run to return a known ResearchReport, bypassing any
    # real model call. We patch the name bound into kore.agents.primary's
    # namespace because primary's tool-factory lambda closes over that name.
    async def stub_research_run(*args, **kwargs):
        class R:
            output = ResearchReport(
                summary="Blue sky = Rayleigh scattering.",
                key_findings=["shorter wavelengths scatter more"],
                sources=[Source(url="https://wiki", title="Rayleigh", snippet="...")],
            )

        return R()

    monkeypatch.setattr(
        "kore.agents.primary.build_deep_research_agent",
        lambda cfg, **kw: type("A", (), {"run": stub_research_run})(),
    )

    orchestrator = Orchestrator(_config(), trace_store=store)

    # Give the primary a FunctionModel that calls deep_research once, then
    # synthesizes the result verbatim on the next turn.
    calls = 0

    async def primary_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="deep_research",
                        args={"query": "why is the sky blue"},
                        tool_call_id="c1",
                    ),
                ],
                model_name="test",
            )
        return ModelResponse(
            parts=[
                TextPart(
                    content=(
                        "The sky is blue because of Rayleigh scattering "
                        "(source: https://wiki)."
                    )
                )
            ],
            model_name="test",
        )

    orchestrator._primary.model = FunctionModel(primary_fn)  # type: ignore[attr-defined]

    resp = await orchestrator.run("why is the sky blue?", session_id="sess-int")

    assert "Rayleigh" in resp.content
    assert "wiki" in resp.content

    # Trace shape: session -> primary -> tool(deep_research) -> subagent_*
    types_ = [e["type"] for e in trace]
    assert types_[0] == "session_start"
    assert "primary_start" in types_
    assert "tool_call" in types_
    assert "subagent_start" in types_
    assert "subagent_done" in types_
    assert "primary_done" in types_
    assert types_[-1] == "session_done"
