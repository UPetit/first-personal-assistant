from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kore.session.buffer import SessionBuffer
from kore.session.compactor import Compactor
from kore.llm.types import KoreMessage


@pytest.fixture
def kore_home(tmp_path, monkeypatch):
    """Patch KORE_HOME so buffer reads/writes go to tmp_path."""
    import kore.session.buffer as buf_mod
    import kore.config as config_mod
    monkeypatch.setattr(config_mod, "KORE_HOME", tmp_path)
    monkeypatch.setattr(buf_mod, "KORE_HOME", tmp_path)
    return tmp_path


def test_new_session_created(kore_home):
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    assert buf._session_id == session_id
    assert buf._turns == []
    assert buf._summary is None


def test_session_roundtrip(kore_home):
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf.append("user", "hello")
    buf.append("assistant", "hi there")
    buf.save()

    buf2 = SessionBuffer.load(session_id)
    assert len(buf2._turns) == 2
    assert buf2._turns[0]["content"] == "hello"
    assert buf2._turns[1]["content"] == "hi there"


def test_history_returns_kore_messages(kore_home):
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf.append("user", "question")
    buf.append("assistant", "answer")

    history = buf.history()
    assert len(history) == 2
    assert all(isinstance(m, KoreMessage) for m in history)
    assert history[0].role == "user"
    assert history[0].content == "question"
    assert history[1].role == "assistant"


def test_history_includes_summary(kore_home):
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf._summary = "Previous context: user asked about Python."
    buf.append("user", "follow up")

    history = buf.history()
    assert len(history) == 2
    assert history[0].content.startswith("[Session summary]")
    assert "Python" in history[0].content
    assert history[1].content == "follow up"


def test_history_summary_timestamp(kore_home):
    """Summary block timestamp equals oldest turn's timestamp."""
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf._summary = "some summary"
    buf.append("user", "first message")
    buf.append("assistant", "first reply")

    history = buf.history()
    summary_ts = history[0].timestamp
    first_turn_ts = history[1].timestamp
    assert summary_ts == first_turn_ts


def test_atomic_save(kore_home):
    """save() writes a .tmp file then renames — no .tmp files left on disk."""
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf.append("user", "test")
    buf.save()

    sess_dir = kore_home / "workspace" / "sessions"
    tmp_files = list(sess_dir.glob("*.tmp"))
    json_files = list(sess_dir.glob("*.json"))
    assert tmp_files == []
    assert len(json_files) == 1


def test_corrupt_session_starts_fresh(kore_home):
    """Corrupt session file triggers a fresh empty buffer, not a crash."""
    session_id = str(uuid4())
    sess_dir = kore_home / "workspace" / "sessions"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / f"{session_id}.json").write_text("not valid json{{{{")

    buf = SessionBuffer.load(session_id)
    assert buf._turns == []


@pytest.mark.asyncio
async def test_compaction_triggers_at_threshold(kore_home, sample_config_with_agents):
    """compact_if_needed calls compactor when token estimate exceeds threshold."""
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)

    # Fill turns to exceed default threshold of 6000 tokens (~24000 chars)
    for i in range(30):
        buf.append("user", "x" * 500)
        buf.append("assistant", "y" * 500)

    mock_compactor = AsyncMock(spec=Compactor)
    mock_compactor.summarise = AsyncMock(return_value="Compacted summary.")

    await buf.compact_if_needed(sample_config_with_agents, compactor=mock_compactor)

    mock_compactor.summarise.assert_called_once()
    assert buf._summary == "Compacted summary."


@pytest.mark.asyncio
async def test_compaction_keeps_recent_turns(kore_home, sample_config_with_agents):
    """After compaction, only the last keep_recent_turns turns remain."""
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)

    for i in range(30):
        buf.append("user", "x" * 500)
        buf.append("assistant", "y" * 500)

    total_before = len(buf._turns)

    mock_compactor = AsyncMock(spec=Compactor)
    mock_compactor.summarise = AsyncMock(return_value="Summary.")
    await buf.compact_if_needed(sample_config_with_agents, compactor=mock_compactor)

    keep = sample_config_with_agents.session.keep_recent_turns
    assert len(buf._turns) == keep
    assert total_before > keep


@pytest.mark.asyncio
async def test_compaction_merges_summary(kore_home, sample_config_with_agents):
    """Second compaction passes existing summary to compactor for merging."""
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf._summary = "Existing summary."

    for i in range(30):
        buf.append("user", "x" * 500)
        buf.append("assistant", "y" * 500)

    mock_compactor = AsyncMock(spec=Compactor)
    mock_compactor.summarise = AsyncMock(return_value="Merged summary.")
    await buf.compact_if_needed(sample_config_with_agents, compactor=mock_compactor)

    call_args = mock_compactor.summarise.call_args
    existing_summary_arg = call_args.args[0]
    assert existing_summary_arg == "Existing summary."
    assert buf._summary == "Merged summary."


@pytest.mark.asyncio
async def test_no_compaction_below_threshold(kore_home, sample_config_with_agents):
    """compact_if_needed does nothing when below the token threshold."""
    session_id = str(uuid4())
    buf = SessionBuffer.load(session_id)
    buf.append("user", "hello")
    buf.append("assistant", "hi")

    mock_compactor = AsyncMock(spec=Compactor)
    mock_compactor.summarise = AsyncMock(return_value="Summary.")
    await buf.compact_if_needed(sample_config_with_agents, compactor=mock_compactor)

    mock_compactor.summarise.assert_not_called()
    assert buf._summary is None
