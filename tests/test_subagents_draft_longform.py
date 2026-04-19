from __future__ import annotations

import pytest

from kore.agents.subagents.draft_longform import (
    build_draft_longform_agent,
    make_draft_longform_tool,
)
from kore.config import SubAgentConfig, UsageLimitsConfig


@pytest.fixture
def subagent_config(test_env) -> SubAgentConfig:
    return SubAgentConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt="prompts/draft_longform.md",
        tools=["memory_search", "read_file"],
        skills=["content-writer"],
        usage_limits=UsageLimitsConfig(
            request_limit=6, total_tokens_limit=60_000, tool_calls_limit=8
        ),
    )


@pytest.mark.asyncio
async def test_build_draft_longform_agent_str_output(subagent_config, sample_config):
    agent = build_draft_longform_agent(
        subagent_config, kore_config=sample_config, skill_registry=None
    )
    assert agent.output_type is str


@pytest.mark.asyncio
async def test_draft_longform_tool_returns_text(koredeps):
    async def fake_run(*args, **kwargs):
        class R:
            output = "a fully drafted paragraph.\n\nSecond paragraph follows."
        return R()

    tool = make_draft_longform_tool(
        agent_factory=lambda: type("A", (), {"run": fake_run})()
    )

    class _Ctx:
        def __init__(self):
            self.deps = koredeps
            class _Usage:
                def incr(self, usage, /):
                    pass
            self.usage = _Usage()

    result = await tool(
        _Ctx(),
        brief="Write two paragraphs explaining why the sky is blue.",
        audience=None,
        constraints=None,
    )
    assert isinstance(result, str)
    assert "drafted paragraph" in result


@pytest.mark.asyncio
async def test_draft_longform_tool_catches_exception(koredeps):
    async def raiser(*args, **kwargs):
        raise RuntimeError("boom")

    tool = make_draft_longform_tool(
        agent_factory=lambda: type("A", (), {"run": raiser})()
    )

    class _Ctx:
        def __init__(self):
            self.deps = koredeps
            class _Usage:
                def incr(self, usage, /):
                    pass
            self.usage = _Usage()

    result = await tool(_Ctx(), brief="x")
    assert isinstance(result, str)
    assert result.startswith("Subagent failed:")
