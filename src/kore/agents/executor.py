from __future__ import annotations

import os
from pathlib import Path

from kore.agents.base import BaseAgent
from kore.config import KoreConfig
from kore.llm.provider import get_model
from kore.tools.registry import get_tools

_PROMPTS_DIR = Path(os.environ.get("KORE_PROMPTS_DIR") or Path(__file__).parents[3] / "prompts")


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text()


def create_executor(
    name: str,
    config: KoreConfig,
    skill_registry=None,  # SkillRegistry | None — avoids circular import at module level
) -> BaseAgent:
    """Create a BaseAgent for the named executor from config.

    Raises KeyError if the executor name is not in config.agents.executors.
    If *skill_registry* is provided and the executor has a non-empty skills list,
    the system prompt is extended with the Level 1 skill summary (always) and
    the Level 2 always-on skill bodies.
    """
    exec_cfg = config.agents.executors[name]  # raises KeyError if unknown
    model = get_model(exec_cfg.model, config)
    prompt = _load_prompt(exec_cfg.prompt_file)
    # Import tool modules to trigger self-registration before get_tools() lookup
    import kore.tools.web_search    # noqa: F401
    import kore.tools.scrape        # noqa: F401
    import kore.tools.time_tool     # noqa: F401
    import kore.tools.memory_tools  # noqa: F401
    try:
        import kore.tools.file_rw  # noqa: F401
    except ImportError:
        pass
    try:
        import kore.tools.cron_tools  # noqa: F401
    except ImportError:
        pass
    tools = get_tools(exec_cfg.tools)

    # Inject skill context into system prompt
    if skill_registry is not None and exec_cfg.skills:
        skills = skill_registry.get_skills_for_executor(
            exec_cfg.skills, available_tools=exec_cfg.tools
        )
        if skills:
            level1 = skill_registry.build_level1_summary()
            skill_context = f"\n\n## Available Skills\n\n{level1}"
            level2 = skill_registry.build_level2_context(skills)
            if level2:
                skill_context += (
                    f"\n\n## Always-Active Skill Instructions\n\n{level2}"
                )
            prompt = prompt + skill_context

    return BaseAgent(
        model,
        exec_cfg.model,
        prompt,
        tools=tools,
        max_retries=exec_cfg.max_retries,
        max_tool_calls=config.security.max_tool_calls_per_request,
    )
