from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from pydantic import ValidationError as PydanticValidationError

KORE_HOME: Path = Path.home() / ".kore"


class ConfigError(Exception):
    """Raised for config loading/validation errors not caught by Pydantic."""


class SecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_tool_calls_per_request: int = 15
    queue_maxsize: int = 100


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Forward-compat stub for Phase 5 (Web UI). No HTTP server started in Phase 1.
    port: int = 8000
    host: str = "0.0.0.0"


class DebugConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_tracing: bool = False


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    compaction_model: str = "anthropic:claude-haiku-4-5-20251001"
    compaction_token_threshold: int = 6000
    keep_recent_turns: int = 10


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    builtin_dir: str = "skills"          # relative to project root
    user_dir: str | None = None          # None → KORE_HOME / "workspace/skills"
    clawhub_base_url: str = "https://clawhub.dev/api/v1"


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bot_token_env: str | None = None
    bot_token: SecretStr | None = None
    webhook_url_env: str | None = None
    webhook_url: str | None = None  # plain str — webhook URLs are not secrets
    allowed_user_ids: list[int] = []


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timezone: str = "UTC"
    data_jobs_file: str = "data/jobs.json"


class ChannelsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    telegram: TelegramConfig | None = None


class CoreMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = "data/core_memory.json"  # relative to KORE_HOME
    max_tokens: int = 4000


class EventLogConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vector_weight: float = 0.7
    bm25_weight: float = 0.3
    decay_half_life_days: int = 60
    top_k: int = 10
    min_importance: float = 0.0


class ConsolidationConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "anthropic:claude-haiku-4-5-20251001"
    interval_minutes: int = 30
    gc_days: int = 90
    gc_min_importance: float = 0.3
    compress_after_days: int = 30


class MemoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    core: CoreMemoryConfig = CoreMemoryConfig()
    event_log: EventLogConfig = EventLogConfig()
    consolidation: ConsolidationConfig = ConsolidationConfig()
    embeddings_model: str = "all-MiniLM-L6-v2"


class LLMProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key_env: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: dict[str, LLMProviderConfig]


class ToolConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str | None = None    # Forward-compat stub. Not read in Phase 1.
    api_key_env: str | None = None
    api_key: SecretStr | None = None
    max_results: int = 5


class UsageLimitsConfig(BaseModel):
    """Caps passed to Pydantic AI's UsageLimits on each agent run.

    These protect against runaway cost. Subagent tokens propagate via ctx.usage
    so a primary's limit covers the whole run tree.
    """
    model_config = ConfigDict(extra="ignore")

    request_limit: int = 30          # max LLM requests per run
    total_tokens_limit: int = 200_000
    tool_calls_limit: int = 25


class PrimaryAgentConfig(BaseModel):
    """The single conversational agent that runs every turn."""
    model_config = ConfigDict(extra="ignore")

    model: str
    prompt: str                                # path to prompt markdown, relative to project root
    tools: list[str] = ["*"]                   # "*" = all registered tools
    skills: list[str] = ["*"]                  # "*" = all discovered skills; plain strings only (no always-override here)
    shell_allowlist: list[str] = []
    usage_limits: UsageLimitsConfig = UsageLimitsConfig()
    max_retries: int = 3

    @field_validator("model")
    @classmethod
    def model_has_provider_prefix(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(
                f"model string must have provider prefix (e.g. 'anthropic:claude-...'): {v!r}"
            )
        return v


class SubAgentConfig(BaseModel):
    """A narrow subagent exposed as an @agent.tool on the primary.

    Currently only 'deep_research' and 'draft_longform' are supported in v2.
    """
    model_config = ConfigDict(extra="ignore")

    model: str
    prompt: str
    tools: list[str]
    skills: list[str] = []
    shell_allowlist: list[str] = []
    usage_limits: UsageLimitsConfig = UsageLimitsConfig()
    max_retries: int = 3

    @field_validator("model")
    @classmethod
    def model_has_provider_prefix(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError(
                f"model string must have provider prefix (e.g. 'anthropic:claude-...'): {v!r}"
            )
        return v


class AgentsConfig(BaseModel):
    """v2 agents schema: one primary + a dict of subagents."""
    model_config = ConfigDict(extra="forbid")

    primary: PrimaryAgentConfig
    subagents: dict[str, SubAgentConfig] = {}

    @field_validator("subagents")
    @classmethod
    def only_known_subagents(cls, v: dict[str, SubAgentConfig]) -> dict[str, SubAgentConfig]:
        allowed = {"deep_research", "draft_longform"}
        unknown = set(v) - allowed
        if unknown:
            raise ValueError(
                f"Unknown subagent(s): {sorted(unknown)}. "
                f"v2 supports only: {sorted(allowed)}"
            )
        return v


class KoreConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str
    llm: LLMConfig
    agents: AgentsConfig | None = None
    tools: dict[str, ToolConfig] = {}
    security: SecurityConfig = SecurityConfig()
    ui: UIConfig = UIConfig()
    session: SessionConfig = SessionConfig()
    skills: SkillsConfig = SkillsConfig()
    memory: MemoryConfig = MemoryConfig()
    channels: ChannelsConfig = ChannelsConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    debug: DebugConfig = DebugConfig()


def _resolve_env_vars(data: Any) -> Any:
    """Walk the raw dict tree. For keys ending in '_env' with a non-null string value,
    resolve the named environment variable and replace the key (stripping '_env' suffix)
    with its value. Raises ConfigError if the env var is absent or empty.
    """
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            if key.endswith("_env") and isinstance(value, str) and value:
                env_value = os.environ.get(value)
                if not env_value:
                    raise ConfigError(
                        f"Required environment variable {value!r} "
                        f"(for config field {key!r}) is not set or empty."
                    )
                target_key = key[:-4]  # "api_key_env" → "api_key"
                result[target_key] = env_value
                # do not include the _env key itself
            else:
                result[key] = _resolve_env_vars(value)
        return result
    elif isinstance(data, list):
        return [_resolve_env_vars(item) for item in data]
    return data


def load_config(path: Path | str | None = None) -> KoreConfig:
    """Load and validate config.json, resolving all *_env references to SecretStr values.

    Loads ~/.kore/.env via python-dotenv before parsing so that *_env fields
    can reference vars set there without requiring them to be in the process environment.
    Defaults to ~/.kore/config.json if path is not given.
    """
    resolved_path = Path(path) if path is not None else KORE_HOME / "config.json"
    load_dotenv(KORE_HOME / ".env", override=False)   # don't override already-set env vars

    with open(resolved_path) as f:
        raw = json.load(f)

    # Detect legacy v1 schema and raise with a migration pointer.
    agents = raw.get("agents") or {}
    legacy_keys = [k for k in ("planner", "executors") if k in agents]
    if legacy_keys:
        raise ConfigError(
            f"Legacy v1 config keys present: agents.{legacy_keys}. "
            "These were removed in the v2 primary-agent refactor. "
            "Migrate to agents.primary + agents.subagents — see "
            "docs/superpowers/specs/2026-04-19-primary-agent-refactor-design.md"
        )

    if "agents" in raw and "primary" not in agents:
        raise ConfigError(
            "agents.primary is required — see the v2 schema in "
            "docs/superpowers/specs/2026-04-19-primary-agent-refactor-design.md"
        )

    resolved = _resolve_env_vars(raw)

    try:
        return KoreConfig.model_validate(resolved)
    except PydanticValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc
