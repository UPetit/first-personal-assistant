from __future__ import annotations

import os
from pathlib import Path

from kore.agents.base import BaseAgent
from kore.config import KoreConfig
from kore.config import KORE_HOME as _DEFAULT_KORE_HOME
from kore.llm.provider import get_model
from kore.tools.registry import get_tools

_PROMPTS_DIR = Path(os.environ.get("KORE_PROMPTS_DIR") or Path(__file__).parents[3] / "prompts")


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text()


def _load_persona(kore_home: Path) -> str:
    """Load SOUL.md and USER.md from kore_home, returning combined content.

    Files are joined with '---' separators. Missing or empty files are skipped.
    Returns empty string if both files are absent or empty.
    """
    parts = []
    for filename in ("SOUL.md", "USER.md"):
        path = kore_home / filename
        if path.exists():
            content = path.read_text().strip()
            if content:
                parts.append(content)
    return "\n\n---\n\n".join(parts)


def create_executor(
    name: str,
    config: KoreConfig,
    skill_registry=None,  # SkillRegistry | None — avoids circular import at module level
    kore_home: Path | None = None,
) -> BaseAgent:
    """Create a BaseAgent for the named executor from config.

    Raises KeyError if the executor name is not in config.agents.executors.
    If *skill_registry* is provided, the system prompt is extended with the Level 1
    skill summary (always) and the Level 2 always-on skill bodies.  An empty
    ``skills`` list in the executor config is treated as ``["*"]`` (load all
    skills whose dependencies are satisfied).
    """
    exec_cfg = config.agents.executors[name]  # raises KeyError if unknown
    model = get_model(exec_cfg.model, config)
    prompt = _load_prompt(exec_cfg.prompt_file)
    # Prepend SOUL.md + USER.md persona context (if present)
    if kore_home is None:
        kore_home = _DEFAULT_KORE_HOME
    persona = _load_persona(kore_home)
    if persona:
        prompt = persona + "\n\n---\n\n" + prompt
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
    try:
        import kore.tools.skill_tools  # noqa: F401
    except ImportError:
        pass
    try:
        import kore.tools.shell  # noqa: F401
    except ImportError:
        pass
    tools = get_tools(exec_cfg.tools)

    # Inject skill context into system prompt
    # Empty skills list means "load all" (wildcard) — explicit exclusion is not supported.
    injected_skills: list[str] = []
    if skill_registry is not None:
        assignments = exec_cfg.skills  # list[SkillAssignment]
        skill_names = [a.name for a in assignments] if assignments else ["*"]
        always_map: dict[str, bool] | None = (
            {a.name: a.always for a in assignments} if assignments else None
        )
        skills = skill_registry.get_skills_for_executor(
            skill_names, available_tools=exec_cfg.tools
        )
        if skills:
            level1 = skill_registry.build_level1_summary()
            skill_context = f"\n\n## Available Skills\n\n{level1}"
            level2 = skill_registry.build_level2_context(skills, always_map=always_map)
            if level2:
                skill_context += (
                    f"\n\n## Always-Active Skill Instructions\n\n{level2}"
                )
            prompt = prompt + skill_context
            injected_skills = [s.name for s in skills]

    agent = BaseAgent(
        model,
        exec_cfg.model,
        prompt,
        tools=tools,
        max_retries=exec_cfg.max_retries,
        max_tool_calls=config.security.max_tool_calls_per_request,
    )
    agent.skills_loaded = injected_skills
    return agent
