from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, RunContext, UsageLimits

from kore.agents.deps import KoreDeps
from kore.config import KoreConfig, SubAgentConfig
from kore.llm.provider import get_model
from kore.tools.registry import get_tools

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(os.environ.get("KORE_PROMPTS_DIR") or Path(__file__).parents[4] / "prompts")


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text()


def build_draft_longform_agent(
    config: SubAgentConfig,
    *,
    kore_config: KoreConfig,
    skill_registry: Any = None,
) -> Agent[KoreDeps, str]:
    """Build the draft_longform Pydantic AI Agent (freeform string output).

    Caller must pass kore_config so model auth flows through Kore's provider
    config rather than ambient env vars.
    """
    import kore.tools.memory_tools  # noqa: F401
    try:
        import kore.tools.file_rw  # noqa: F401
    except ImportError:
        pass

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

    agent: Agent[KoreDeps, str] = Agent(
        model,
        system_prompt=prompt,
        tools=tools,
        output_type=str,
        retries=config.max_retries,
        deps_type=KoreDeps,
    )
    return agent


def make_draft_longform_tool(
    *,
    agent_factory: Callable[[], Agent[KoreDeps, str]],
    usage_limits: UsageLimits | None = None,
):
    """Build an @agent.tool for long-form drafting.

    Returns the draft text on success, or a "Subagent failed: ..." string
    on any unhandled exception.
    """
    async def draft_longform(
        ctx: RunContext[KoreDeps],
        brief: str,
        audience: str | None = None,
        constraints: str | None = None,
    ) -> str:
        """Delegate a long-form writing task. Returns the finished draft as text.

        Args:
            brief: What to write, including topic and approximate length.
            audience: Who the draft is for (e.g., "technical recruiters", "my team").
            constraints: Hard requirements (word count, format, must-include points).
        """
        sub_agent = agent_factory()
        parts = [brief]
        if audience:
            parts.append(f"Audience: {audience}")
        if constraints:
            parts.append(f"Constraints: {constraints}")
        message = "\n\n".join(parts)
        try:
            result = await sub_agent.run(
                message,
                deps=ctx.deps,
                usage=ctx.usage,
                usage_limits=usage_limits,
            )
            return result.output
        except Exception as exc:  # noqa: BLE001
            logger.warning("draft_longform subagent raised: %s", exc, exc_info=True)
            return f"Subagent failed: {exc!s}"

    return draft_longform
