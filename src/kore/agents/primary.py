from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, UsageLimits

from kore.agents.deps import KoreDeps
from kore.agents.subagents import (
    build_deep_research_agent,
    build_draft_longform_agent,
    make_deep_research_tool,
    make_draft_longform_tool,
)
from kore.agents.system_prompts import current_time_fragment
from kore.config import (
    KORE_HOME as _DEFAULT_KORE_HOME,
    KoreConfig,
    PrimaryAgentConfig,
    SubAgentConfig,
    UsageLimitsConfig,
)
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


def _usage_limits(cfg: UsageLimitsConfig) -> UsageLimits:
    return UsageLimits(
        request_limit=cfg.request_limit,
        total_tokens_limit=cfg.total_tokens_limit,
        tool_calls_limit=cfg.tool_calls_limit,
    )


def build_primary(
    *,
    primary_config: PrimaryAgentConfig,
    subagents: dict[str, SubAgentConfig],
    kore_config: KoreConfig,
    skill_registry: Any = None,
    kore_home: Path | None = None,
) -> Agent[KoreDeps, str]:
    """Build the single conversational primary Agent.

    The primary holds the full conversation, reads skills, calls tools directly,
    and delegates narrow tasks to subagents (deep_research, draft_longform) that
    are exposed as @agent.tool wrappers.

    ``kore_config`` is required so model auth flows through Kore's provider
    config rather than ambient env vars, and so subagent agents share the same
    auth path.
    """
    # Trigger tool module registration
    import kore.tools.web_search    # noqa: F401
    import kore.tools.scrape        # noqa: F401
    import kore.tools.time_tool     # noqa: F401
    import kore.tools.memory_tools  # noqa: F401
    import kore.tools.file_rw       # noqa: F401
    import kore.tools.cron_tools    # noqa: F401
    import kore.tools.skill_tools   # noqa: F401
    import kore.tools.shell         # noqa: F401

    kore_home = kore_home or _DEFAULT_KORE_HOME
    prompt = _load_prompt(Path(primary_config.prompt).name)
    persona = _load_persona(kore_home)
    if persona:
        prompt = persona + "\n\n---\n\n" + prompt

    injected_skills: list[str] = []
    if skill_registry is not None:
        skills_list = primary_config.skills if primary_config.skills else ["*"]
        skills = skill_registry.get_skills_for_executor(
            skills_list, available_tools=primary_config.tools
        )
        if skills:
            level1 = skill_registry.build_level1_summary()
            skill_context = f"\n\n## Available Skills\n\n{level1}"
            level2 = skill_registry.build_level2_context(skills, always_map=None)
            if level2:
                skill_context += f"\n\n## Always-Active Skill Instructions\n\n{level2}"
            prompt = prompt + skill_context
            injected_skills = [s.name for s in skills]

    model = get_model(primary_config.model, kore_config)
    tools = get_tools(primary_config.tools)

    agent: Agent[KoreDeps, str] = Agent(
        model,
        system_prompt=prompt,
        tools=tools,
        output_type=str,
        retries=primary_config.max_retries,
        deps_type=KoreDeps,
    )

    agent.system_prompt(current_time_fragment)

    if "deep_research" in subagents:
        sub_cfg = subagents["deep_research"]
        sub_limits = _usage_limits(sub_cfg.usage_limits)
        agent.tool(
            make_deep_research_tool(
                agent_factory=lambda cfg=sub_cfg: build_deep_research_agent(
                    cfg, skill_registry=skill_registry, kore_config=kore_config
                ),
                usage_limits=sub_limits,
            )
        )

    if "draft_longform" in subagents:
        sub_cfg = subagents["draft_longform"]
        sub_limits = _usage_limits(sub_cfg.usage_limits)
        agent.tool(
            make_draft_longform_tool(
                agent_factory=lambda cfg=sub_cfg: build_draft_longform_agent(
                    cfg, skill_registry=skill_registry, kore_config=kore_config
                ),
                usage_limits=sub_limits,
            )
        )

    # --- Orchestrator metadata contract ---
    # The three `_kore_*` attributes below are the public contract read by the
    # orchestrator (see kore/agents/orchestrator.py). The underscore prefix scopes
    # these attributes within Kore's namespace on the foreign pydantic-ai Agent
    # class to avoid collisions with upstream attributes. Removing or renaming
    # any of these is a breaking change to the orchestrator.
    #   _kore_skills_loaded: list[str]   - names of skills injected at build time
    #   _kore_model_string: str          - the original provider:model string
    #   _kore_usage_limits: UsageLimits  - caps applied to each primary run
    agent._kore_skills_loaded = injected_skills  # type: ignore[attr-defined]
    agent._kore_model_string = primary_config.model  # type: ignore[attr-defined]
    agent._kore_usage_limits = _usage_limits(primary_config.usage_limits)  # type: ignore[attr-defined]
    return agent
