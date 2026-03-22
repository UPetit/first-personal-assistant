from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kore.scheduler.cron import KoreCronScheduler

from kore.tools.registry import register

logger = logging.getLogger(__name__)

_scheduler: KoreCronScheduler | None = None


def init(scheduler: KoreCronScheduler) -> None:
    """Inject the scheduler dependency. Call from main.py before serving requests."""
    global _scheduler
    _scheduler = scheduler


async def cron_create(
    job_id: str,
    schedule: str,
    prompt: str,
    executor: str = "general",
    timezone: str | None = None,
) -> str:
    """Create or replace a scheduled cron job.

    Args:
        job_id: Unique identifier (e.g. 'daily_digest')
        schedule: 5-field cron expression (e.g. '0 8 * * *' for 8am daily)
        prompt: Message to send when the job fires
        executor: Executor to handle the message (default: 'general')
        timezone: IANA timezone string (e.g. 'Europe/Paris'); defaults to system timezone

    Returns:
        Confirmation string with job_id and schedule
    """
    if _scheduler is None:
        return "Error: scheduler not initialized"
    try:
        _scheduler.add_job(job_id, schedule, prompt, source="telegram",
                           executor=executor, timezone=timezone)
        return f"Job '{job_id}' scheduled: {schedule}"
    except Exception as e:
        return f"Error scheduling job: {e}"


async def cron_list() -> str:
    """List all scheduled cron jobs.

    Returns:
        Formatted list of jobs with their next run times.
    """
    if _scheduler is None:
        return "Error: scheduler not initialized"
    jobs = _scheduler.list_jobs()
    if not jobs:
        return "No scheduled jobs."
    lines = [f"- {j['id']}: next_run={j['next_run_at']}" for j in jobs]
    return "\n".join(lines)


async def cron_delete(job_id: str) -> str:
    """Delete a scheduled cron job by ID.

    Args:
        job_id: The job ID to delete

    Returns:
        Confirmation or error message
    """
    if _scheduler is None:
        return "Error: scheduler not initialized"
    try:
        _scheduler.remove_job(job_id)
        return f"Job '{job_id}' deleted."
    except KeyError:
        return f"Error: job '{job_id}' not found."
    except Exception as e:
        return f"Error removing job '{job_id}': {e}"


register("cron_create", cron_create)
register("cron_list", cron_list)
register("cron_delete", cron_delete)
