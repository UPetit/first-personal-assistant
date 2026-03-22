from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
async def db_engine(tmp_path):
    from kore.db.database import create_engine, setup_schema
    engine = create_engine(tmp_path / "test.db")
    await setup_schema(engine)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_db_creates_events_table(db_engine):
    from sqlalchemy import text
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='events'")
        )
        assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_db_creates_fts5_table(db_engine):
    from sqlalchemy import text
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'")
        )
        assert result.fetchone() is not None


@pytest.mark.asyncio
async def test_db_can_insert_event(db_engine):
    import time
    from sqlalchemy import text
    async with db_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO events (timestamp, category, content, source, importance) "
                "VALUES (:ts, :cat, :content, :source, :imp)"
            ),
            {"ts": time.time(), "cat": "fact", "content": "test fact", "source": "user", "imp": 0.7},
        )
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM events"))
        assert result.scalar() == 1


def test_memory_config_defaults():
    from kore.config import MemoryConfig
    cfg = MemoryConfig()
    assert cfg.core.path == "data/core_memory.json"
    assert cfg.core.max_tokens == 4000
    assert cfg.event_log.vector_weight == 0.7
    assert cfg.event_log.bm25_weight == 0.3
    assert cfg.event_log.decay_half_life_days == 60
    assert cfg.consolidation.model == "anthropic:claude-haiku-4-5-20251001"


def test_kore_config_has_memory_field():
    from kore.config import MemoryConfig, KoreConfig, LLMConfig, LLMProviderConfig
    from pydantic import SecretStr
    cfg = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={"anthropic": LLMProviderConfig(api_key=SecretStr("k"))}),
    )
    assert hasattr(cfg, "memory")
    assert isinstance(cfg.memory, MemoryConfig)


# ── core memory tests ─────────────────────────────────────────────────────────

def test_core_memory_starts_empty(tmp_path):
    from kore.memory.core_memory import CoreMemory
    cm = CoreMemory(tmp_path / "core_memory.json")
    assert cm.get() == {}


def test_core_memory_update_and_get(tmp_path):
    from kore.memory.core_memory import CoreMemory
    cm = CoreMemory(tmp_path / "core_memory.json")
    cm.update("user.name", "Alice")
    assert cm.get()["user"]["name"] == "Alice"


def test_core_memory_update_nested(tmp_path):
    from kore.memory.core_memory import CoreMemory
    cm = CoreMemory(tmp_path / "core_memory.json")
    cm.update("projects.kore.status", "active")
    cm.update("projects.kore.started", "2026-01")
    assert cm.get()["projects"]["kore"]["status"] == "active"
    assert cm.get()["projects"]["kore"]["started"] == "2026-01"


def test_core_memory_delete(tmp_path):
    from kore.memory.core_memory import CoreMemory
    cm = CoreMemory(tmp_path / "core_memory.json")
    cm.update("user.name", "Alice")
    cm.delete("user.name")
    assert "name" not in cm.get().get("user", {})


def test_core_memory_delete_missing_key_is_noop(tmp_path):
    from kore.memory.core_memory import CoreMemory
    cm = CoreMemory(tmp_path / "core_memory.json")
    cm.delete("nonexistent.key")  # should not raise


def test_core_memory_persists_to_disk(tmp_path):
    from kore.memory.core_memory import CoreMemory
    path = tmp_path / "core_memory.json"
    cm1 = CoreMemory(path)
    cm1.update("user.name", "Bob")

    # Re-load from same path
    cm2 = CoreMemory(path)
    assert cm2.get()["user"]["name"] == "Bob"


def test_core_memory_token_cap_enforced(tmp_path):
    from kore.memory.core_memory import CoreMemory, TokenCapExceeded
    cm = CoreMemory(tmp_path / "core_memory.json", max_tokens=10)
    with pytest.raises(TokenCapExceeded):
        cm.update("key", "x" * 1000)


def test_core_memory_token_cap_rollback_on_failure(tmp_path):
    from kore.memory.core_memory import CoreMemory, TokenCapExceeded
    cm = CoreMemory(tmp_path / "core_memory.json", max_tokens=50)
    cm.update("a", "short")
    try:
        cm.update("b", "x" * 5000)
    except TokenCapExceeded:
        pass
    # Original data should be unchanged
    assert cm.get().get("a") == "short"
    assert "b" not in cm.get()


def test_core_memory_loads_existing_file(tmp_path):
    import json
    path = tmp_path / "core_memory.json"
    path.write_text(json.dumps({"user": {"name": "Carol"}}))
    from kore.memory.core_memory import CoreMemory
    cm = CoreMemory(path)
    assert cm.get()["user"]["name"] == "Carol"
