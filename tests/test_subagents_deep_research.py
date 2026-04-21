from __future__ import annotations

import pytest

from kore.agents.deps import KoreDeps
from kore.agents.subagents.deep_research import (
    build_deep_research_agent,
    make_deep_research_tool,
)
from kore.config import SubAgentConfig, UsageLimitsConfig
from kore.llm.types import ResearchReport, Source


@pytest.fixture
def subagent_config(test_env) -> SubAgentConfig:
    return SubAgentConfig(
        model="anthropic:claude-haiku-4-5-20251001",
        prompt="prompts/deep_research.md",
        tools=["web_search", "scrape_url", "memory_search"],
        skills=["search-topic-online"],
        usage_limits=UsageLimitsConfig(
            request_limit=10, total_tokens_limit=80_000, tool_calls_limit=12
        ),
    )


@pytest.mark.asyncio
async def test_build_deep_research_agent_sets_result_type(subagent_config, koredeps, sample_config):
    agent = build_deep_research_agent(
        subagent_config, kore_config=sample_config, skill_registry=None
    )
    assert agent.output_type is ResearchReport  # pydantic-ai attribute


@pytest.mark.asyncio
async def test_deep_research_tool_returns_report(subagent_config, koredeps, monkeypatch):
    # Replace model at test time with a TestModel that emits a structured ResearchReport
    fake_report = ResearchReport(
        summary="Sample summary.",
        key_findings=["A", "B"],
        sources=[Source(url="https://x", title="X", snippet="s")],
    )

    async def fake_run(*args, **kwargs):
        class R:
            output = fake_report
            def usage(self):
                class U:
                    request_tokens = 10
                    response_tokens = 10
                    total_tokens = 20
                    requests = 1
                return U()
        return R()

    # Build the tool wrapper pointing at a stub agent
    tool = make_deep_research_tool(agent_factory=lambda: type("A", (), {"run": fake_run})())

    class _Ctx:
        def __init__(self):
            self.deps = koredeps
            class _Usage:
                def incr(self, usage, /):
                    pass
            self.usage = _Usage()

    result = await tool(_Ctx(), query="why is the sky blue?", focus=None)
    assert isinstance(result, ResearchReport)
    assert result.summary == "Sample summary."


@pytest.mark.asyncio
async def test_deep_research_tool_catches_exception(subagent_config, koredeps):
    async def raiser(*args, **kwargs):
        raise RuntimeError("boom")

    tool = make_deep_research_tool(agent_factory=lambda: type("A", (), {"run": raiser})())

    class _Ctx:
        def __init__(self):
            self.deps = koredeps
            class _Usage:
                def incr(self, usage, /):
                    pass
            self.usage = _Usage()

    result = await tool(_Ctx(), query="x", focus=None)
    # Failure path returns a string placeholder that the primary sees as the tool result.
    assert isinstance(result, str)
    assert result.startswith("Subagent failed:")
    assert "boom" in result
