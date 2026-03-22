from __future__ import annotations

import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel as OpenAIModel

from kore.config import ConfigError, KoreConfig, LLMConfig, LLMProviderConfig
from kore.llm.provider import get_model


def _make_config(**providers: dict) -> KoreConfig:
    """Build a KoreConfig with the given provider configs."""
    return KoreConfig(
        version="1.0.0",
        llm=LLMConfig(
            providers={
                name: LLMProviderConfig(**cfg) for name, cfg in providers.items()
            }
        ),
    )


def test_anthropic_prefix():
    config = _make_config(anthropic={"api_key": SecretStr("test-key")})
    model = get_model("anthropic:claude-sonnet-4-6", config)
    assert isinstance(model, AnthropicModel)


def test_openai_prefix():
    config = _make_config(openai={"api_key": SecretStr("test-key")})
    model = get_model("openai:gpt-4o", config)
    assert isinstance(model, OpenAIModel)


def test_openrouter_prefix():
    config = _make_config(openrouter={"api_key": SecretStr("test-key")})
    model = get_model("openrouter:anthropic/claude-sonnet-4-6", config)
    assert isinstance(model, OpenAIModel)


def test_ollama_prefix():
    config = _make_config()  # ollama requires no API key
    model = get_model("ollama:qwen3:8b", config)
    assert isinstance(model, OpenAIModel)


def test_unknown_prefix_raises():
    config = _make_config()
    with pytest.raises(ValueError, match="Unknown provider"):
        get_model("groq:llama-3-70b", config)


def test_missing_provider_config_raises():
    config = _make_config()  # empty providers dict
    with pytest.raises(ConfigError, match="'anthropic' not found"):
        get_model("anthropic:claude-sonnet-4-6", config)
