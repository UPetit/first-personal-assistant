from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel as OpenAIModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from kore.config import ConfigError, KoreConfig


def get_model(model_string: str, config: KoreConfig) -> Model:
    """Parse a provider-prefixed model string and return a Pydantic AI Model instance.

    Supported formats:
        anthropic:<model-id>    → AnthropicModel
        openai:<model-id>       → OpenAIModel (native endpoint)
        openrouter:<model-id>   → OpenAIModel (base_url=openrouter.ai)
        ollama:<model-id>       → OpenAIModel (base_url=localhost:11434)

    Raises:
        ValueError: provider prefix not recognised.
        ConfigError: provider block missing from config.llm.providers (where required).
    """
    if ":" not in model_string:
        raise ValueError(
            f"Invalid model string {model_string!r}: must be '<provider>:<model-id>'"
        )

    prefix, model_id = model_string.split(":", 1)
    providers = config.llm.providers

    if prefix == "anthropic":
        cfg = providers.get("anthropic")
        if cfg is None:
            raise ConfigError("Provider 'anthropic' not found in config.llm.providers")
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        return AnthropicModel(model_id, provider=AnthropicProvider(api_key=api_key))

    elif prefix == "openai":
        cfg = providers.get("openai")
        if cfg is None:
            raise ConfigError("Provider 'openai' not found in config.llm.providers")
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        return OpenAIModel(model_id, provider=OpenAIProvider(api_key=api_key))

    elif prefix == "openrouter":
        cfg = providers.get("openrouter")
        if cfg is None:
            raise ConfigError("Provider 'openrouter' not found in config.llm.providers")
        api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
        base_url = (cfg.base_url if cfg.base_url else None) or "https://openrouter.ai/api/v1"
        return OpenAIModel(
            model_id,
            provider=OpenAIProvider(api_key=api_key, base_url=base_url),
        )

    elif prefix == "ollama":
        cfg = providers.get("ollama")
        base_url = (cfg.base_url if cfg else None) or "http://localhost:11434/v1"
        return OpenAIModel(
            model_id,
            provider=OpenAIProvider(api_key="ollama", base_url=base_url),
        )

    else:
        raise ValueError(
            f"Unknown provider: {prefix!r}. Supported: anthropic, openai, openrouter, ollama"
        )
