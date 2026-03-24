from __future__ import annotations

from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
from kore.tools.registry import register


async def skill_search(ctx: RunContext[KoreDeps], query: str) -> str:
    """Search ClawHub for skills matching the query.

    Returns a list of matching skill names and descriptions.
    """
    from kore.skills.clawhub import ClawHubClient

    client = ClawHubClient(base_url=ctx.deps.config.skills.clawhub_base_url)
    results = await client.search(query)
    if not results:
        return "No skills found on ClawHub for that query."
    lines = [f"- {r.name}: {r.description}" for r in results]
    return "\n".join(lines)


register("skill_search", skill_search)


async def skill_install(ctx: RunContext[KoreDeps], skill_name: str) -> str:
    """Install a skill from ClawHub into the user skill directory.

    After installation the skill registry is reloaded automatically,
    making the new skill immediately available without a restart.
    """
    from kore.skills.clawhub import ClawHubClient, ClawHubError

    registry = ctx.deps.skill_registry
    if registry is None:
        return "Skill registry not available — cannot install skills."

    client = ClawHubClient(base_url=ctx.deps.config.skills.clawhub_base_url)
    try:
        skill_dir = await client.install(skill_name, registry.user_dir)
    except ClawHubError as exc:
        return f"Install failed: {exc}"

    registry.reload()
    return f"Skill '{skill_name}' installed to {skill_dir} and registry reloaded."


register("skill_install", skill_install)
