from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

import kore.tools.cron_tools as cron_tools


@pytest.fixture(autouse=True)
def reset_scheduler():
    cron_tools._scheduler = None
    yield
    cron_tools._scheduler = None


def _make_scheduler(jobs=None):
    sched = MagicMock()
    sched.list_jobs.return_value = jobs or []
    return sched


# 1. cron_list empty
@pytest.mark.asyncio
async def test_cron_list_empty():
    cron_tools.init(_make_scheduler())
    result = await cron_tools.cron_list()
    assert "No scheduled jobs" in result


# 2. cron_list with jobs
@pytest.mark.asyncio
async def test_cron_list_with_jobs():
    sched = _make_scheduler([{"id": "daily", "next_run_at": "2026-03-22T08:00:00+00:00",
                               "schedule": "0 8 * * *", "prompt": "Do digest",
                               "source": "telegram"}])
    cron_tools.init(sched)
    result = await cron_tools.cron_list()
    assert "daily" in result


# 3. cron_create calls add_job with source="telegram" and prompt
@pytest.mark.asyncio
async def test_cron_create_passes_source_telegram():
    sched = _make_scheduler()
    cron_tools.init(sched)
    result = await cron_tools.cron_create("my_job", "0 8 * * *", "Do something")
    sched.add_job.assert_called_once_with(
        "my_job", "0 8 * * *", "Do something",
        source="telegram", executor="general", timezone=None,
    )
    assert "my_job" in result


# 4. cron_create with explicit executor and timezone
@pytest.mark.asyncio
async def test_cron_create_custom_executor_timezone():
    sched = _make_scheduler()
    cron_tools.init(sched)
    await cron_tools.cron_create("j2", "0 9 * * *", "msg", executor="digest", timezone="Europe/Paris")
    sched.add_job.assert_called_once_with(
        "j2", "0 9 * * *", "msg",
        source="telegram", executor="digest", timezone="Europe/Paris",
    )


# 5. cron_create returns error string when add_job raises
@pytest.mark.asyncio
async def test_cron_create_error():
    sched = _make_scheduler()
    sched.add_job.side_effect = ValueError("bad cron")
    cron_tools.init(sched)
    result = await cron_tools.cron_create("j", "not valid", "msg")
    assert "Error" in result


# 6. cron_delete calls remove_job and returns confirmation
@pytest.mark.asyncio
async def test_cron_delete_existing_job():
    sched = _make_scheduler()
    cron_tools.init(sched)
    result = await cron_tools.cron_delete("my_job")
    sched.remove_job.assert_called_once_with("my_job")
    assert "my_job" in result
    assert "deleted" in result.lower()


# 7. cron_delete returns error string (not raise) when job not found
@pytest.mark.asyncio
async def test_cron_delete_not_found():
    sched = _make_scheduler()
    sched.remove_job.side_effect = KeyError("ghost")
    cron_tools.init(sched)
    result = await cron_tools.cron_delete("ghost")
    assert "not found" in result.lower() or "error" in result.lower()


# 8. All tools return error string when scheduler not initialized
@pytest.mark.asyncio
async def test_tools_uninitialized():
    cron_tools._scheduler = None
    r1 = await cron_tools.cron_list()
    r2 = await cron_tools.cron_create("x", "0 * * * *", "msg")
    r3 = await cron_tools.cron_delete("x")
    assert all("Error" in r for r in [r1, r2, r3])


# 9. prompt (not message) used in cron_create signature
@pytest.mark.asyncio
async def test_cron_create_uses_prompt_not_message():
    import inspect
    sig = inspect.signature(cron_tools.cron_create)
    assert "prompt" in sig.parameters
    assert "message" not in sig.parameters
