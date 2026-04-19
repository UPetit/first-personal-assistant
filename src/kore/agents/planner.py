from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from kore.agents.base import BaseAgent
from kore.config import ConfigError, KoreConfig
from kore.llm.provider import get_model

# KORE_PROMPTS_DIR is set to /app/prompts in the Docker image.
# In development (editable install) it falls back to the project root's prompts/ dir.
_PROMPTS_DIR = Path(os.environ.get("KORE_PROMPTS_DIR") or Path(__file__).parents[3] / "prompts")


class PlanStep(BaseModel):
    executor: str       # must match a key in config.agents.executors
    instruction: str    # what this executor should do


class PlanResult(BaseModel):
    intent: str         # one-line description of what the user wants
    reasoning: str      # why these steps/executors were chosen
    steps: list[PlanStep] = Field(min_length=1)


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text()


def _build_executors_summary(config: KoreConfig) -> str:
    names = list(config.agents.executors.keys())
    lines = [
        f"## Available executors",
        f"",
        f"Valid executor names — you MUST use EXACTLY one of: {names}",
        f"Do NOT invent names like 'browser', 'assistant', 'chat', 'writer', or any other value not in the list above.",
        "",
        "## Executor descriptions",
    ]
    for name, cfg in config.agents.executors.items():
        desc = cfg.description or f"Executor for {name} tasks"
        tools = ", ".join(cfg.tools or [])
        lines.append(f"- {name!r}: {desc}")
        if tools:
            lines.append(f"  Tools: {tools}")
    lines += [
        "",
        "## Tool routing",
        "Use the executor whose tool list contains what the step needs:",
    ]
    for name, cfg in config.agents.executors.items():
        for tool in (cfg.tools or []):
            lines.append(f"  {tool} → use {name!r}")
    lines += [
        "",
        "## Routing examples — map task descriptions to executor names",
        "  'Browse this URL / go to X / scrape / check this page' → look for executor with scrape_url",
        "  'Search the web / find recent info / look up X online' → look for executor with web_search",
        "  'Write / draft / compose / summarise text' → look for executor with memory/writing tools",
        "  'Remember / save / recall / what did I say about X' → look for executor with memory tools",
        "",
        "CRITICAL: Never invent executor names based on the task description.",
        "The task may say 'browse' or 'search' — that is the task, not the executor name.",
        f"The ONLY valid executor names are: {list(config.agents.executors.keys())}",
    ]
    return "\n".join(lines)


def create_planner(config: KoreConfig) -> BaseAgent:
    if config.agents.planner is None:
        raise ConfigError("Planner not configured — add agents.planner to config.json")
    summary = _build_executors_summary(config)
    prompt = _load_prompt(config.agents.planner.prompt_file).replace("{{EXECUTORS}}", summary)
    model = get_model(config.agents.planner.model, config)
    return BaseAgent(
        model,
        config.agents.planner.model,
        prompt,
        output_type=PlanResult,
        max_retries=config.agents.planner.max_retries,
        max_tool_calls=config.security.max_tool_calls_per_request,
    )
