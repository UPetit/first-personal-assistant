from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext, UsageLimits

from kore.agents.deps import KoreDeps
from kore.agents.system_prompts import current_time_fragment
from kore.config import KoreConfig, SubAgentConfig
from kore.llm.provider import get_model
from kore.llm.types import ResearchReport
from kore.tools.registry import get_tools

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(os.environ.get("KORE_PROMPTS_DIR") or Path(__file__).parents[4] / "prompts")


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text()


def build_deep_research_agent(
    config: SubAgentConfig,
    *,
    kore_config: KoreConfig,
    skill_registry: Any = None,
) -> Agent[KoreDeps, ResearchReport]:
    """Build the deep_research Pydantic AI Agent.

    Caller must pass ``kore_config`` so model auth flows through Kore's provider
    config rather than ambient env vars.

    The returned agent has:
    - output_type = ResearchReport (structured return contract)
    - tools limited to config.tools (narrow allowlist)
    - skills injected from the registry, if any are assigned
    """
    # Trigger tool module registration
    import kore.tools.web_search    # noqa: F401
    import kore.tools.scrape        # noqa: F401
    import kore.tools.memory_tools  # noqa: F401

    model = get_model(config.model, kore_config)
    prompt = _load_prompt(Path(config.prompt).name)

    if skill_registry is not None and config.skills:
        skills = skill_registry.get_skills_for_executor(
            config.skills, available_tools=config.tools
        )
        if skills:
            level2 = skill_registry.build_level2_context(skills, always_map=None)
            if level2:
                prompt = prompt + "\n\n## Skill Instructions\n\n" + level2

    tools = get_tools(config.tools)

    agent: Agent[KoreDeps, ResearchReport] = Agent(
        model,
        system_prompt=prompt,
        tools=tools,
        output_type=ResearchReport,
        retries=config.max_retries,
        deps_type=KoreDeps,
    )
    agent.system_prompt(current_time_fragment)
    return agent


def make_deep_research_tool(
    *,
    agent_factory: Callable[[], Agent[KoreDeps, ResearchReport]],
    usage_limits: UsageLimits | None = None,
):
    """Build an @agent.tool compatible async function that delegates to the subagent.

    The returned coroutine signature matches what Pydantic AI expects for a tool:
    the first arg is the RunContext, remaining args become the JSON-schema parameters
    visible to the primary.

    The wrapper propagates ctx.usage so the primary's UsageLimits cap the whole
    run tree (subagent token usage counts against the primary's budget).

    On any unhandled exception, the wrapper returns a string starting with
    "Subagent failed:" so the primary sees the failure and can retry or abandon
    without crashing the turn.
    """
    async def deep_research(
        ctx: RunContext[KoreDeps],
        query: str,
        focus: str | None = None,
    ) -> ResearchReport | str:
        """Delegate a research task. Returns a structured ResearchReport with cited sources.

        Args:
            query: The research question, fully specified.
            focus: Optional narrowing (e.g., "policy debate only", "post-2024 sources").
        """
        sub_agent = agent_factory()
        message = query if not focus else f"{query}\n\nFocus: {focus}"
        try:
            result = await sub_agent.run(
                message,
                deps=ctx.deps,
                usage=ctx.usage,           # propagate parent usage tally
                usage_limits=usage_limits,
            )
            return result.output
        except Exception as exc:  # noqa: BLE001 — the boundary is intentional
            logger.warning("deep_research subagent raised: %s", exc, exc_info=True)
            return f"Subagent failed: {exc!s}"

    return deep_research
