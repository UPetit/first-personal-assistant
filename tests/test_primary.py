from __future__ import annotations

from pathlib import Path

import pytest

from kore.agents.primary import build_primary
from kore.config import PrimaryAgentConfig, SubAgentConfig


def _primary_cfg() -> PrimaryAgentConfig:
    return PrimaryAgentConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt="prompts/primary.md",
        tools=["memory_search", "web_search", "scrape_url", "read_file"],
        skills=["*"],
    )


def _research_cfg() -> SubAgentConfig:
    return SubAgentConfig(
        model="anthropic:claude-haiku-4-5-20251001",
        prompt="prompts/deep_research.md",
        tools=["web_search", "scrape_url", "memory_search"],
    )


def _draft_cfg() -> SubAgentConfig:
    return SubAgentConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt="prompts/draft_longform.md",
        tools=["memory_search", "read_file"],
    )


@pytest.mark.asyncio
async def test_primary_builds_with_subagent_tools(sample_config, tmp_path):
    kore_home = tmp_path / "kore"
    kore_home.mkdir()

    agent = build_primary(
        primary_config=_primary_cfg(),
        subagents={"deep_research": _research_cfg(), "draft_longform": _draft_cfg()},
        skill_registry=None,
        kore_config=sample_config,
        kore_home=kore_home,
    )

    registered_tools = {t.name for t in agent._function_toolset.tools.values()}  # type: ignore[attr-defined]
    assert "deep_research" in registered_tools
    assert "draft_longform" in registered_tools


@pytest.mark.asyncio
async def test_primary_persona_prepended(sample_config, tmp_path):
    kore_home = tmp_path / "kore"
    kore_home.mkdir()
    (kore_home / "SOUL.md").write_text("TEST-SOUL-CONTENT")
    (kore_home / "USER.md").write_text("TEST-USER-CONTENT")

    agent = build_primary(
        primary_config=_primary_cfg(),
        subagents={},
        skill_registry=None,
        kore_config=sample_config,
        kore_home=kore_home,
    )
    prompts = agent._system_prompts  # type: ignore[attr-defined]
    combined = "\n".join(prompts)
    assert "TEST-SOUL-CONTENT" in combined
    assert "TEST-USER-CONTENT" in combined


@pytest.mark.asyncio
async def test_primary_missing_persona_is_silent(sample_config, tmp_path):
    kore_home = tmp_path / "kore"
    kore_home.mkdir()

    agent = build_primary(
        primary_config=_primary_cfg(),
        subagents={},
        skill_registry=None,
        kore_config=sample_config,
        kore_home=kore_home,
    )
    prompts = agent._system_prompts  # type: ignore[attr-defined]
    combined = "\n".join(prompts)
    assert combined
