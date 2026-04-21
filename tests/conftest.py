from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from kore.agents.deps import KoreDeps
from kore.config import (
    KoreConfig,
    LLMConfig,
    LLMProviderConfig,
    ToolConfig,
)


@pytest.fixture
def test_env(monkeypatch):
    """Set required env vars. Does NOT set TELEGRAM_BOT_TOKEN (added in Phase 5)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("BRAVE_API_KEY", "test-brave-key")


@pytest.fixture
def sample_config():
    """Pre-built KoreConfig with resolved SecretStr keys (bypasses load_config)."""
    return KoreConfig(
        version="1.0.0",
        llm=LLMConfig(
            providers={
                "anthropic": LLMProviderConfig(api_key=SecretStr("test-anthropic-key")),
                "openai": LLMProviderConfig(api_key=SecretStr("test-openai-key")),
                "openrouter": LLMProviderConfig(api_key=SecretStr("test-openrouter-key")),
            }
        ),
        tools={
            "web_search": ToolConfig(api_key=SecretStr("test-brave-key"), max_results=5),
        },
    )


@pytest.fixture
def mock_deps(sample_config):
    """Simulates a pydantic-ai RunContext for direct tool unit tests.
    Access pattern: ctx.deps.config — mirrors real RunContext where ctx.deps is the deps object.
    """
    return SimpleNamespace(deps=KoreDeps(config=sample_config))


@pytest.fixture
def kore_home(tmp_path, monkeypatch):
    """Redirect KORE_HOME and session buffer module to tmp_path."""
    import kore.session.buffer as buf_mod
    import kore.config as config_mod

    monkeypatch.setattr(config_mod, "KORE_HOME", tmp_path)
    monkeypatch.setattr(buf_mod, "KORE_HOME", tmp_path)
    return tmp_path


@pytest.fixture
async def memory_deps(tmp_path, sample_config):
    """Fixture providing a full memory stack (CoreMemory + EventLog) for tool tests."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from kore.db.database import create_engine, setup_schema
    from kore.memory.core_memory import CoreMemory
    from kore.memory.embeddings import EmbeddingModel
    from kore.memory.event_log import EventLog
    from kore.memory.retrieval import Retriever

    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)

    mock_em = MagicMock(spec=EmbeddingModel)
    mock_em.embed = AsyncMock(return_value=None)

    core_mem = CoreMemory(tmp_path / "core_memory.json")
    event_log = EventLog(engine, mock_em)
    retriever = Retriever(event_log, mock_em)

    deps = KoreDeps(
        config=sample_config,
        core_memory=core_mem,
        event_log=event_log,
        retriever=retriever,
    )
    yield SimpleNamespace(deps=deps)
    await engine.dispose()


@pytest.fixture
def koredeps(sample_config):
    from kore.agents.deps import KoreDeps
    return KoreDeps(config=sample_config)
