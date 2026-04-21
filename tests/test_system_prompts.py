from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic_ai.models.test import TestModel

from kore.agents.primary import build_primary
from kore.agents.subagents.deep_research import build_deep_research_agent
from kore.agents.subagents.draft_longform import build_draft_longform_agent
from kore.agents.system_prompts import current_time_fragment
from kore.config import PrimaryAgentConfig, SubAgentConfig
from kore.llm.types import ResearchReport


def test_current_time_fragment_contains_todays_utc_date():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fragment = current_time_fragment()
    assert today in fragment
    assert "UTC" in fragment


def _collect_system_prompt(messages) -> str:
    from pydantic_ai.messages import ModelRequest, SystemPromptPart

    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, SystemPromptPart):
                    parts.append(part.content)
    return "\n".join(parts)


@pytest.mark.asyncio
async def test_primary_injects_current_time(sample_config, tmp_path):
    cfg = PrimaryAgentConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt="prompts/primary.md",
        tools=["memory_search"],
        skills=["*"],
    )
    agent = build_primary(
        primary_config=cfg,
        subagents={},
        skill_registry=None,
        kore_config=sample_config,
        kore_home=tmp_path,
    )
    agent.model = TestModel(call_tools=[])
    result = await agent.run("hello")
    combined = _collect_system_prompt(result.all_messages())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in combined


@pytest.mark.asyncio
async def test_deep_research_injects_current_time(sample_config, test_env):
    cfg = SubAgentConfig(
        model="anthropic:claude-haiku-4-5-20251001",
        prompt="prompts/deep_research.md",
        tools=["web_search", "scrape_url", "memory_search"],
    )
    agent = build_deep_research_agent(cfg, kore_config=sample_config)
    agent.model = TestModel(
        call_tools=[],
        custom_output_args={
            "summary": "s",
            "key_findings": ["a"],
            "sources": [],
        },
    )
    result = await agent.run("question")
    combined = _collect_system_prompt(result.all_messages())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in combined
    assert isinstance(result.output, ResearchReport)


@pytest.mark.asyncio
async def test_draft_longform_injects_current_time(sample_config, test_env):
    cfg = SubAgentConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt="prompts/draft_longform.md",
        tools=["memory_search", "read_file"],
    )
    agent = build_draft_longform_agent(cfg, kore_config=sample_config)
    agent.model = TestModel(call_tools=[])
    result = await agent.run("write something")
    combined = _collect_system_prompt(result.all_messages())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in combined
