from __future__ import annotations

import pytest
from pydantic_ai.models.test import TestModel

from kore.agents.executor import create_executor


def test_create_executor_general(sample_config_with_agents):
    agent = create_executor("general", sample_config_with_agents)
    assert agent._model_string == "anthropic:claude-sonnet-4-6"
    tool_names = list(agent._agent._function_toolset.tools.keys())
    assert "web_search" in tool_names
    assert "scrape_url" in tool_names
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "get_current_time" in tool_names


def test_create_executor_search(sample_config_with_agents):
    agent = create_executor("search", sample_config_with_agents)
    assert agent._model_string == "anthropic:claude-haiku-4-5-20251001"
    tool_names = list(agent._agent._function_toolset.tools.keys())
    assert "web_search" in tool_names
    assert "scrape_url" in tool_names
    assert "read_file" not in tool_names


def test_create_executor_general_file_tools(sample_config_with_agents):
    agent = create_executor("general", sample_config_with_agents)
    tool_names = list(agent._agent._function_toolset.tools.keys())
    assert "read_file" in tool_names
    assert "write_file" in tool_names


def test_unknown_executor_raises(sample_config_with_agents):
    with pytest.raises(KeyError):
        create_executor("nonexistent", sample_config_with_agents)


@pytest.mark.asyncio
async def test_executor_run_returns_response(mock_deps):
    """Executor returns AgentResponse when run with TestModel (no real LLM)."""
    from pydantic_ai.models.test import TestModel
    from kore.agents.base import BaseAgent
    from kore.llm.types import AgentResponse

    model = TestModel()
    agent = BaseAgent(model, "test:model", "you are an executor")
    result = await agent.run("do something", deps=mock_deps)
    assert isinstance(result, AgentResponse)
    assert result.content
    assert result.output is None  # no output_type


def test_create_executor_injects_level1_summary(tmp_path, sample_config_with_agents):
    """Executor system prompt includes Level 1 skill summary when registry is provided."""
    from kore.skills.registry import SkillRegistry
    from kore.config import ExecutorConfig

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()

    # Write a skill with no tool deps so it passes dep check for any executor
    skill_dir = builtin / "web-research"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        '---\nname: web-research\ndescription: Search the web\n'
        'metadata: \'{"kore":{"always":false,"requires":{"tools":[]}}}\'\n---\n# Body'
    )

    registry = SkillRegistry(builtin, user)
    # Give 'general' executor a wildcard skills config
    cfg = sample_config_with_agents.model_copy(deep=True)
    cfg.agents.executors["general"] = ExecutorConfig(
        model=cfg.agents.executors["general"].model,
        prompt_file=cfg.agents.executors["general"].prompt_file,
        tools=cfg.agents.executors["general"].tools,
        skills=["*"],
        description=cfg.agents.executors["general"].description,
    )

    agent = create_executor("general", cfg, skill_registry=registry)
    prompt = agent._agent._system_prompts[0]

    assert "<skills>" in prompt
    assert "web-research" in prompt


def test_create_executor_injects_level2_always_on(tmp_path, sample_config_with_agents):
    """Always-on skill body is included in executor system prompt."""
    from kore.skills.registry import SkillRegistry
    from kore.config import ExecutorConfig

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()

    skill_dir = builtin / "memory-management"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        '---\nname: memory-management\ndescription: Memory rules\n'
        'metadata: \'{"kore":{"always":true,"requires":{}}}\'\n---\n# Memory Instructions\nAlways active.'
    )

    registry = SkillRegistry(builtin, user)
    cfg = sample_config_with_agents.model_copy(deep=True)
    cfg.agents.executors["general"] = ExecutorConfig(
        model=cfg.agents.executors["general"].model,
        prompt_file=cfg.agents.executors["general"].prompt_file,
        tools=cfg.agents.executors["general"].tools,
        skills=["*"],
        description=cfg.agents.executors["general"].description,
    )

    agent = create_executor("general", cfg, skill_registry=registry)
    prompt = agent._agent._system_prompts[0]

    assert "Always active." in prompt


def test_create_executor_no_skills_when_registry_absent(sample_config_with_agents):
    """No skill content injected when no registry passed (backward compat)."""
    agent = create_executor("general", sample_config_with_agents)
    prompt = agent._agent._system_prompts[0]

    assert "<skills>" not in prompt


def test_create_executor_level2_scoped_to_executor_skills(tmp_path, sample_config_with_agents):
    """Always-on skills not in executor's skill list are excluded from Level 2."""
    from kore.skills.registry import SkillRegistry
    from kore.agents.executor import create_executor
    from kore.config import ExecutorConfig

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    # memory-management is always-on but NOT in the executor's explicit skill list
    for skill_name, always in [("web-research", False), ("memory-management", True)]:
        skill_dir = builtin / skill_name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f'---\nname: {skill_name}\ndescription: {skill_name}\n'
            f'metadata: \'{{"kore":{{"always":{str(always).lower()},"requires":{{}}}}}}\'\n---\n'
            f'# {skill_name} body\nContent for {skill_name}.'
        )

    registry = SkillRegistry(builtin, user)
    cfg = sample_config_with_agents.model_copy(deep=True)
    cfg.agents.executors["search"] = ExecutorConfig(
        model=cfg.agents.executors["search"].model,
        prompt_file=cfg.agents.executors["search"].prompt_file,
        tools=cfg.agents.executors["search"].tools,
        skills=["web-research"],  # explicit: only web-research, NOT memory-management
        description=cfg.agents.executors["search"].description,
    )

    agent = create_executor("search", cfg, skill_registry=registry)
    prompt = agent._agent._system_prompts[0]

    # memory-management always-on body should NOT appear (not in skill list)
    assert "memory-management body" not in prompt
    # web-research is not always-on, so it appears only in Level 1 XML
    assert "web-research" in prompt
