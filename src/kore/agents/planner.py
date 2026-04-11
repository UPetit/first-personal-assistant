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
        f"Valid executor names (use EXACTLY one of these): {names}",
        "",
        "Tool-to-executor mapping (which executor to use when a task requires a given tool):",
    ]
    for name, cfg in config.agents.executors.items():
        for tool in (cfg.tools or []):
            lines.append(f"  {tool} → {name!r}")
    lines += [
        "",
        "Executor descriptions:",
    ]
    for name, cfg in config.agents.executors.items():
        desc = cfg.description or f"Executor for {name} tasks"
        lines.append(f"- {name!r}: {desc}")
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
