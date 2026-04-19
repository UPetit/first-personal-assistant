from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from kore.config import (
    AgentsConfig,
    ChannelsConfig,
    ConfigError,
    ExecutorConfig,
    KoreConfig,
    LLMConfig,
    LLMProviderConfig,
    SchedulerConfig,
    SecurityConfig,
    TelegramConfig,
    ToolConfig,
    UIConfig,
    load_config,
)


def _minimal_config_dict() -> dict:
    """Minimal valid config.json content."""
    return {
        "version": "1.0.0",
        "llm": {
            "providers": {
                "anthropic": {"api_key": "test-key"},
            }
        },
    }


def test_valid_config_loads(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(_minimal_config_dict()))
    config = load_config(str(cfg_path))
    assert config.version == "1.0.0"


def test_missing_version_fails(tmp_path):
    data = _minimal_config_dict()
    del data["version"]
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    with pytest.raises(ConfigError):
        load_config(str(cfg_path))


def test_env_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "brave-secret")
    data = {
        "version": "1.0.0",
        "llm": {"providers": {}},
        "tools": {"web_search": {"api_key_env": "BRAVE_API_KEY"}},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    config = load_config(str(cfg_path))
    assert isinstance(config.tools["web_search"].api_key, SecretStr)
    assert config.tools["web_search"].api_key.get_secret_value() == "brave-secret"
    # The _env field must be cleared after resolution to prevent logging the var name
    assert config.tools["web_search"].api_key_env is None


def test_missing_env_var_fails(tmp_path, monkeypatch):
    # Use a unique env var name that cannot be present in any .env file on disk.
    # load_config calls load_dotenv(~/.kore/.env) internally, so we must not use a
    # var that may already be defined there (e.g. BRAVE_API_KEY).
    missing_var = "KORE_TEST_MISSING_VAR_XYZ_12345"
    monkeypatch.delenv(missing_var, raising=False)
    data = {
        "version": "1.0.0",
        "llm": {"providers": {}},
        "tools": {"web_search": {"api_key_env": missing_var}},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    with pytest.raises(ConfigError, match=missing_var):
        load_config(str(cfg_path))


def test_invalid_model_string_fails(tmp_path):
    data = _minimal_config_dict()
    data["agents"] = {
        "executors": {
            "general": {
                "model": "claude-sonnet-no-prefix",   # missing "anthropic:" prefix
                "prompt_file": "prompts/general.md",
                "tools": [],
            }
        }
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    with pytest.raises(ConfigError):
        load_config(str(cfg_path))


def test_unknown_keys_ignored(tmp_path):
    data = _minimal_config_dict()
    data["future_feature"] = {"some": "data"}
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    config = load_config(str(cfg_path))
    assert config.version == "1.0.0"


def test_default_values(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(_minimal_config_dict()))
    config = load_config(str(cfg_path))
    assert config.security.max_tool_calls_per_request == 15
    assert config.ui.port == 8000


def test_security_config_defaults():
    sec = SecurityConfig()
    assert sec.max_tool_calls_per_request == 15
    assert sec.queue_maxsize == 100


def test_executor_max_retries_default():
    """ExecutorConfig.max_retries defaults to 3."""
    cfg = ExecutorConfig(model="anthropic:claude-sonnet-4-6", prompt_file="x.md", tools=[])
    assert cfg.max_retries == 3


def test_executor_max_retries_custom():
    """ExecutorConfig.max_retries can be overridden."""
    cfg = ExecutorConfig(model="anthropic:claude-sonnet-4-6", prompt_file="x.md", tools=[], max_retries=5)
    assert cfg.max_retries == 5


def test_planner_optional(tmp_path):
    data = _minimal_config_dict()
    data["agents"] = {}  # no planner block
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    config = load_config(str(cfg_path))
    assert config.agents.planner is None


def test_executor_skills_accepted(tmp_path):
    data = _minimal_config_dict()
    data["agents"] = {
        "executors": {
            "general": {
                "model": "anthropic:claude-haiku-4-5-20251001",
                "prompt_file": "prompts/general.md",
                "tools": ["web_search"],
                "skills": ["web-research"],
            }
        }
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    config = load_config(str(cfg_path))
    from kore.config import SkillAssignment
    assert config.agents.executors["general"].skills == [SkillAssignment(name="web-research", always=False)]


def test_secrets_redacted_in_repr(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "super-secret-key")
    data = {
        "version": "1.0.0",
        "llm": {"providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}}},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(data))
    config = load_config(str(cfg_path))
    assert "super-secret-key" not in repr(config)
    assert "super-secret-key" not in str(config)


def test_session_config_defaults():
    """SessionConfig has sensible defaults."""
    from kore.config import SessionConfig
    cfg = SessionConfig()
    assert cfg.compaction_model == "anthropic:claude-haiku-4-5-20251001"
    assert cfg.compaction_token_threshold == 6000
    assert cfg.keep_recent_turns == 10


def test_executor_description_optional():
    """ExecutorConfig.description is optional with default empty string."""
    from kore.config import ExecutorConfig
    cfg = ExecutorConfig(model="anthropic:claude-sonnet-4-6", prompt_file="x.md", tools=[])
    assert cfg.description == ""
    cfg2 = ExecutorConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt_file="x.md",
        tools=[],
        description="Does things",
    )
    assert cfg2.description == "Does things"


def test_skills_config_defaults():
    """SkillsConfig has sensible defaults."""
    from kore.config import SkillsConfig
    cfg = SkillsConfig()
    assert cfg.builtin_dir == "skills"
    assert cfg.user_dir is None
    assert cfg.clawhub_base_url == "https://clawhub.dev/api/v1"


def test_kore_config_has_skills_field(sample_config):
    """KoreConfig has a skills field of type SkillsConfig."""
    from kore.config import SkillsConfig
    assert hasattr(sample_config, "skills")
    assert isinstance(sample_config.skills, SkillsConfig)


def test_telegram_config_defaults():
    cfg = TelegramConfig()
    assert cfg.allowed_user_ids == []
    assert cfg.bot_token is None
    assert cfg.webhook_url is None


def test_scheduler_config_defaults():
    cfg = SchedulerConfig()
    assert cfg.timezone == "UTC"
    assert cfg.data_jobs_file == "data/jobs.json"
    assert not hasattr(cfg, "seed_file")


def test_kore_config_has_channels_and_scheduler(sample_config):
    assert hasattr(sample_config, "channels")
    assert hasattr(sample_config, "scheduler")
    assert isinstance(sample_config.channels, ChannelsConfig)
    assert isinstance(sample_config.scheduler, SchedulerConfig)


def test_scheduler_config_has_new_fields():
    from kore.config import SchedulerConfig
    cfg = SchedulerConfig()
    assert cfg.data_jobs_file == "data/jobs.json"
    assert not hasattr(cfg, "db_path")
    assert not hasattr(cfg, "seed_file")


def test_telegram_bot_token_env_resolved(monkeypatch, tmp_path):
    """bot_token_env in config is resolved to bot_token SecretStr via _resolve_env_vars."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("TG_TOKEN", "tg-secret-123")
    cfg_data = {
        "version": "1.0.0",
        "llm": {"providers": {"anthropic": {"api_key_env": "ANTHROPIC_API_KEY"}}},
        "channels": {"telegram": {"bot_token_env": "TG_TOKEN", "allowed_user_ids": [111]}},
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg_data))
    cfg = load_config(cfg_file)
    assert cfg.channels.telegram is not None
    assert cfg.channels.telegram.bot_token.get_secret_value() == "tg-secret-123"
    assert cfg.channels.telegram.allowed_user_ids == [111]


def test_debug_config_defaults_session_tracing_false():
    from kore.config import DebugConfig
    cfg = DebugConfig()
    assert cfg.session_tracing is False


def test_kore_config_has_debug_field(sample_config):
    from kore.config import DebugConfig
    assert hasattr(sample_config, "debug")
    assert isinstance(sample_config.debug, DebugConfig)
    assert sample_config.debug.session_tracing is False


def test_debug_session_tracing_can_be_enabled():
    from kore.config import DebugConfig
    cfg = DebugConfig(session_tracing=True)
    assert cfg.session_tracing is True


def test_usage_limits_defaults():
    from kore.config import UsageLimitsConfig
    cfg = UsageLimitsConfig()
    assert cfg.request_limit == 30
    assert cfg.total_tokens_limit == 200_000
    assert cfg.tool_calls_limit == 25


def test_primary_agent_config_requires_model_and_prompt():
    from kore.config import PrimaryAgentConfig, UsageLimitsConfig
    cfg = PrimaryAgentConfig(
        model="anthropic:claude-sonnet-4-6",
        prompt="prompts/primary.md",
    )
    assert cfg.tools == ["*"]
    assert cfg.skills == ["*"]
    assert cfg.shell_allowlist == []
    assert cfg.usage_limits == UsageLimitsConfig()


def test_primary_agent_config_rejects_model_without_prefix():
    from kore.config import PrimaryAgentConfig
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrimaryAgentConfig(model="claude-sonnet", prompt="prompts/primary.md")


def test_subagent_config_narrow_defaults():
    from kore.config import SubAgentConfig
    cfg = SubAgentConfig(
        model="anthropic:claude-haiku-4-5-20251001",
        prompt="prompts/deep_research.md",
        tools=["web_search", "scrape_url"],
        skills=["search-topic-online"],
    )
    assert cfg.shell_allowlist == []
    assert cfg.usage_limits.tool_calls_limit == 25


def test_usage_limits_override():
    from kore.config import SubAgentConfig
    cfg = SubAgentConfig(
        model="anthropic:claude-haiku-4-5-20251001",
        prompt="prompts/deep_research.md",
        tools=["web_search"],
        usage_limits={"tool_calls_limit": 12, "total_tokens_limit": 80_000},
    )
    assert cfg.usage_limits.tool_calls_limit == 12
    assert cfg.usage_limits.total_tokens_limit == 80_000
    assert cfg.usage_limits.request_limit == 30
