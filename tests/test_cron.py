from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

UTC = timezone.utc


def _make_scheduler(tmp_path, *, existing_jobs=None, tz="UTC"):
    """Helper: build a KoreCronScheduler with tmp files."""
    from kore.gateway.queue import MessageQueue
    from kore.scheduler.cron import KoreCronScheduler

    jobs_file = tmp_path / "data" / "jobs.json"

    if existing_jobs is not None:
        jobs_file.parent.mkdir(parents=True, exist_ok=True)
        jobs_file.write_text(json.dumps({"version": 1, "jobs": existing_jobs}))

    queue = MessageQueue()
    scheduler = KoreCronScheduler(
        jobs_file=jobs_file,
        queue=queue,
        timezone=tz,
    )
    return scheduler, queue, jobs_file


def test_stale_tmp_cleaned_on_load(tmp_path):
    _, _, jobs_file = _make_scheduler(tmp_path, existing_jobs=[])
    # Create a stale .tmp file
    tmp = jobs_file.with_suffix(".json.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text('{"garbage": true}')
    from kore.gateway.queue import MessageQueue
    from kore.scheduler.cron import KoreCronScheduler
    sched = KoreCronScheduler(jobs_file=jobs_file, queue=MessageQueue())
    sched.start()
    sched.stop()
    assert not tmp.exists()


# ── next_run_at recompute on startup ───────────────────────────────────────────

def test_past_next_run_recomputed_to_future(tmp_path):
    past = "2020-01-01T08:00:00+00:00"
    existing = [{"id": "j1", "schedule": "0 8 * * *", "prompt": "p", "source": "ui",
                 "executor": "general", "enabled": True, "tz": None,
                 "next_run_at": past, "last_run_at": None, "last_status": None}]
    scheduler, _, jobs_file = _make_scheduler(tmp_path, existing_jobs=existing)
    scheduler.start()
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    stored = data["jobs"][0]["next_run_at"]
    assert stored != past
    assert datetime.fromisoformat(stored) > datetime.now(UTC)


def test_future_next_run_not_changed(tmp_path):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    existing = [{"id": "j1", "schedule": "0 8 * * *", "prompt": "p", "source": "ui",
                 "executor": "general", "enabled": True, "tz": None,
                 "next_run_at": future, "last_run_at": None, "last_status": None}]
    scheduler, _, jobs_file = _make_scheduler(tmp_path, existing_jobs=existing)
    scheduler.start()
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    stored = data["jobs"][0]["next_run_at"]
    assert abs((datetime.fromisoformat(stored) - datetime.fromisoformat(future)).total_seconds()) < 1


# ── add_job ────────────────────────────────────────────────────────────────────

def test_add_job_writes_to_json(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("nightly", "0 2 * * *", "Run nightly", source="telegram")
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    assert any(j["id"] == "nightly" for j in data["jobs"])


def test_add_job_fields_in_json(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "Morning check", source="ui")
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    job = next(j for j in data["jobs"] if j["id"] == "j1")
    assert job["schedule"] == "0 8 * * *"
    assert job["prompt"] == "Morning check"
    assert job["source"] == "ui"
    # executor remains on the dataclass for legacy jobs.json compat, defaulting to "general"
    assert job["executor"] == "general"
    assert job["enabled"] is True
    assert job["next_run_at"] is not None
    assert "tz" in job


def test_add_job_upserts_duplicate_id(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "First")
    scheduler.add_job("j1", "0 9 * * *", "Second")
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    matches = [j for j in data["jobs"] if j["id"] == "j1"]
    assert len(matches) == 1
    assert matches[0]["prompt"] == "Second"


def test_add_job_invalid_cron_raises(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    with pytest.raises(ValueError):
        scheduler.add_job("bad", "not a cron", "msg")
    scheduler.stop()
    # JSON should not have been modified with the bad job
    data = json.loads(jobs_file.read_text())
    assert not any(j["id"] == "bad" for j in data["jobs"])


def test_add_job_unknown_timezone_raises(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    from zoneinfo import ZoneInfoNotFoundError
    with pytest.raises(ZoneInfoNotFoundError):
        scheduler.add_job("j1", "0 8 * * *", "msg", timezone="Not/ATimezone")
    scheduler.stop()
    # JSON should not have been modified with the bad job
    data = json.loads(jobs_file.read_text())
    assert not any(j["id"] == "j1" for j in data["jobs"])


# ── remove_job ─────────────────────────────────────────────────────────────────

def test_remove_job_removes_from_json(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("to_remove", "0 8 * * *", "msg")
    scheduler.remove_job("to_remove")
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    assert not any(j["id"] == "to_remove" for j in data["jobs"])


def test_remove_job_unknown_raises_key_error(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    with pytest.raises(KeyError):
        scheduler.remove_job("ghost")
    scheduler.stop()
    # JSON should be unchanged — no jobs written or removed incorrectly
    data = json.loads(jobs_file.read_text())
    assert not any(j["id"] == "ghost" for j in data["jobs"])


# ── list_jobs ──────────────────────────────────────────────────────────────────

def test_list_jobs_returns_correct_fields(tmp_path):
    scheduler, _, _ = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "Morning", source="telegram")
    jobs = scheduler.list_jobs()
    scheduler.stop()
    assert len(jobs) == 1
    j = jobs[0]
    assert j["id"] == "j1"
    assert j["schedule"] == "0 8 * * *"
    assert j["prompt"] == "Morning"
    assert j["source"] == "telegram"
    assert j["executor"] == "general"
    assert "next_run_at" in j
    assert "last_run_at" in j
    assert "last_status" in j
    assert j["enabled"] is True
    assert j["tz"] is None


# ── run_job_now ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_job_now_pushes_message(tmp_path):
    scheduler, queue, _ = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "Do the thing")
    await scheduler.run_job_now("j1")
    scheduler.stop()
    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg.text == "Do the thing"
    assert msg.session_id == "cron_j1"
    assert msg.user_id == "cron"
    assert msg.channel == "cron"


@pytest.mark.asyncio
async def test_run_job_now_updates_state(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "msg")
    # Capture next_run_at before
    jobs_before = scheduler.list_jobs()
    next_run_before = jobs_before[0]["next_run_at"]
    await scheduler.run_job_now("j1")
    scheduler.stop()
    data = json.loads(jobs_file.read_text())
    job = data["jobs"][0]
    assert job["last_run_at"] is not None
    assert job["last_status"] == "ok"
    # next_run_at must NOT have changed
    assert job["next_run_at"] == next_run_before


@pytest.mark.asyncio
async def test_run_job_now_works_on_disabled_job(tmp_path):
    existing = [{"id": "j1", "schedule": "0 8 * * *", "prompt": "p", "source": "ui",
                 "executor": "general", "enabled": False, "tz": None,
                 "next_run_at": None, "last_run_at": None, "last_status": None}]
    scheduler, queue, _ = _make_scheduler(tmp_path, existing_jobs=existing)
    scheduler.start()
    await scheduler.run_job_now("j1")
    scheduler.stop()
    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_run_job_now_unknown_raises(tmp_path):
    scheduler, _, _ = _make_scheduler(tmp_path)
    scheduler.start()
    with pytest.raises(KeyError):
        await scheduler.run_job_now("ghost")
    scheduler.stop()


# ── timer path ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_job_skipped_by_on_timer(tmp_path):
    existing = [{"id": "j1", "schedule": "0 8 * * *", "prompt": "p", "source": "ui",
                 "executor": "general", "enabled": False, "tz": None,
                 "next_run_at": "2020-01-01T00:00:00+00:00",
                 "last_run_at": None, "last_status": None}]
    scheduler, queue, _ = _make_scheduler(tmp_path, existing_jobs=existing)
    scheduler.start()
    await scheduler._on_timer()
    scheduler.stop()
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_arm_timer_empty_job_list_no_crash(tmp_path):
    scheduler, _, _ = _make_scheduler(tmp_path)
    scheduler.start()
    # Should not raise with no jobs
    scheduler._arm_timer()
    scheduler.stop()


@pytest.mark.asyncio
async def test_on_timer_queue_error_sets_last_status_error(tmp_path):
    from kore.gateway.queue import MessageQueue
    from kore.scheduler.cron import KoreCronScheduler
    import asyncio

    jobs_file = tmp_path / "data" / "jobs.json"
    queue = MessageQueue()
    scheduler = KoreCronScheduler(jobs_file=jobs_file, queue=queue)
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "msg")

    # Force the job to be due now
    scheduler._jobs[0].next_run_at = datetime(2020, 1, 1, tzinfo=UTC)

    # Make queue.put raise
    async def bad_put(msg):
        raise RuntimeError("queue full")
    queue.put = bad_put

    await scheduler._on_timer()
    scheduler.stop()

    import json as _json
    data = _json.loads(jobs_file.read_text())
    assert data["jobs"][0]["last_status"] == "error"


# ── telegram delivery ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_init_sender_reply_calls_send_fn(tmp_path):
    scheduler, _, _ = _make_scheduler(tmp_path)
    send_fn = AsyncMock()
    scheduler.init_sender(send_fn, "12345")
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "msg")
    await scheduler.run_job_now("j1")
    scheduler.stop()

    # Consume message and call reply
    msg = await scheduler._queue.get()
    await msg.reply("response text")
    send_fn.assert_called_once_with("12345", "response text")


@pytest.mark.asyncio
async def test_no_sender_uses_noop_reply(tmp_path):
    scheduler, queue, _ = _make_scheduler(tmp_path)
    # No init_sender called
    scheduler.start()
    scheduler.add_job("j1", "0 8 * * *", "msg")
    await scheduler.run_job_now("j1")
    scheduler.stop()
    msg = await queue.get()
    # Should not raise
    await msg.reply("anything")


def test_cron_create_tool_no_longer_accepts_executor():
    from kore.tools import cron_tools
    import inspect
    sig = inspect.signature(cron_tools.cron_create)
    assert "executor" not in sig.parameters


def test_job_from_dict_tolerates_legacy_executor_field(caplog):
    from kore.scheduler.cron import _job_from_dict
    raw = {
        "id": "legacy_job",
        "schedule": "0 8 * * *",
        "prompt": "ping",
        "executor": "writer",
    }
    with caplog.at_level(logging.WARNING, logger="kore.scheduler.cron"):
        job = _job_from_dict(raw)
    assert job.id == "legacy_job"
    assert any("executor" in r.message.lower() for r in caplog.records)
