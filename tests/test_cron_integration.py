from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

UTC = timezone.utc


def _make_scheduler(tmp_path):
    from kore.gateway.queue import MessageQueue
    from kore.scheduler.cron import KoreCronScheduler
    jobs_file = tmp_path / "data" / "jobs.json"
    queue = MessageQueue()
    scheduler = KoreCronScheduler(jobs_file=jobs_file, queue=queue, timezone="UTC")
    return scheduler, queue, jobs_file


def _near_future(offset_s: float = 0.05):
    """Return a datetime offset_s seconds from now."""
    return datetime.now(UTC) + timedelta(seconds=offset_s)


# 1. Job fires and pushes Message to queue when due
@pytest.mark.asyncio
async def test_job_fires_when_due(tmp_path):
    scheduler, queue, _ = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "* * * * *", "fire me")

    # Override next_run_at to fire in 50ms
    scheduler._jobs[0].next_run_at = _near_future(0.05)
    scheduler._arm_timer()

    await asyncio.sleep(0.15)
    scheduler.stop()

    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg.text == "fire me"


# 2. State written to JSON after execution
@pytest.mark.asyncio
async def test_state_written_after_execution(tmp_path):
    scheduler, _, jobs_file = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "* * * * *", "check state")

    scheduler._jobs[0].next_run_at = _near_future(0.05)
    scheduler._arm_timer()

    await asyncio.sleep(0.15)
    scheduler.stop()

    data = json.loads(jobs_file.read_text())
    job = data["jobs"][0]
    assert job["last_run_at"] is not None
    assert job["last_status"] == "ok"
    assert job["next_run_at"] is not None
    # next_run_at should be in the future after firing
    assert datetime.fromisoformat(job["next_run_at"]) > datetime.now(UTC)


# 3. Multiple overdue jobs all fire before save+rearm
@pytest.mark.asyncio
async def test_multiple_overdue_jobs_all_fire(tmp_path):
    scheduler, queue, _ = _make_scheduler(tmp_path)
    scheduler.start()
    scheduler.add_job("j1", "* * * * *", "job one")
    scheduler.add_job("j2", "* * * * *", "job two")

    past = datetime(2020, 1, 1, tzinfo=UTC)
    scheduler._jobs[0].next_run_at = past
    scheduler._jobs[1].next_run_at = past

    await scheduler._on_timer()
    scheduler.stop()

    assert queue.qsize() == 2


# 4. Adding a job mid-sleep rearms timer; new job fires
@pytest.mark.asyncio
async def test_add_job_mid_sleep_rearms(tmp_path):
    scheduler, queue, _ = _make_scheduler(tmp_path)
    scheduler.start()
    # Add a job with a far-future time so timer sleeps long
    scheduler.add_job("j1", "0 0 1 1 *", "far future")
    scheduler._jobs[0].next_run_at = _near_future(3600)
    scheduler._arm_timer()

    # Add a near-future job — should rearm and fire
    scheduler.add_job("j2", "* * * * *", "near future")
    scheduler._jobs[-1].next_run_at = _near_future(0.05)
    scheduler._arm_timer()

    await asyncio.sleep(0.15)
    scheduler.stop()

    fired_texts = []
    while queue.qsize():
        msg = await queue.get()
        fired_texts.append(msg.text)
    assert "near future" in fired_texts
