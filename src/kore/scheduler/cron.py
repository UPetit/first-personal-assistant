from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kore.channels.base import Message, noop_reply
from kore.gateway.queue import MessageQueue

logger = logging.getLogger(__name__)
UTC = timezone.utc


def _compute_next_run(schedule: str, tz: str, after: datetime) -> datetime:
    """Return the next UTC datetime after `after` for the given cron expression and timezone."""
    zone = ZoneInfo(tz)
    base = after.astimezone(zone)
    it = croniter(schedule, base)
    next_dt = it.get_next(datetime)
    # croniter preserves tzinfo of the start time; convert to UTC
    return next_dt.astimezone(UTC)


@dataclass
class CronJob:
    id: str
    schedule: str
    prompt: str
    source: str = "ui"
    executor: str = "general"
    tz: str | None = None
    enabled: bool = True
    next_run_at: datetime | None = None   # UTC-aware
    last_run_at: datetime | None = None   # UTC-aware
    last_status: str | None = None        # "ok" | "error"


def _job_to_dict(job: CronJob) -> dict:
    return {
        "id": job.id,
        "schedule": job.schedule,
        "prompt": job.prompt,
        "source": job.source,
        "executor": job.executor,
        "tz": job.tz,
        "enabled": job.enabled,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "last_run_at": job.last_run_at.isoformat() if job.last_run_at else None,
        "last_status": job.last_status,
    }


def _job_from_dict(d: dict) -> CronJob:
    def _dt(s: str | None) -> datetime | None:
        if not s:
            return None
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    return CronJob(
        id=d["id"],
        schedule=d["schedule"],
        prompt=d["prompt"],
        source=d.get("source", "ui"),
        executor=d.get("executor", "general"),
        tz=d.get("tz"),
        enabled=d.get("enabled", True),
        next_run_at=_dt(d.get("next_run_at")),
        last_run_at=_dt(d.get("last_run_at")),
        last_status=d.get("last_status"),
    )


class KoreCronScheduler:
    """Asyncio-native cron scheduler. data/jobs.json is the authoritative store."""

    def __init__(
        self,
        jobs_file: Path,
        queue: MessageQueue,
        timezone: str = "UTC",
    ) -> None:
        self._jobs_file = jobs_file
        self._queue = queue
        self._timezone = timezone
        self._jobs: list[CronJob] = []
        self._timer_task: asyncio.Task | None = None
        self._running = False
        self._send_fn: Callable[[str, str], Awaitable[None]] | None = None
        self._default_user_id: str | None = None

    def init_sender(
        self,
        send_fn: Callable[[str, str], Awaitable[None]],
        user_id: str,
    ) -> None:
        """Configure Telegram delivery for cron job results. Call before start()."""
        self._send_fn = send_fn
        self._default_user_id = user_id

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._load()
        self._recompute_next_runs()
        self._save()
        self._running = True
        self._arm_timer()

    def stop(self) -> None:
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    # ── public API ─────────────────────────────────────────────────────────────

    def add_job(
        self,
        job_id: str,
        cron_expr: str,
        prompt: str,
        source: str = "ui",
        executor: str = "general",
        timezone: str | None = None,
    ) -> str:
        """Add or replace a cron job. Returns job_id.

        Raises ValueError for invalid cron expressions.
        Raises ZoneInfoNotFoundError for unknown timezones.
        """
        resolved_tz = timezone or self._timezone
        if timezone:
            ZoneInfo(timezone)  # validate — raises ZoneInfoNotFoundError if bad
        next_run = _compute_next_run(cron_expr, resolved_tz, datetime.now(UTC))
        job = CronJob(
            id=job_id,
            schedule=cron_expr,
            prompt=prompt,
            source=source,
            executor=executor,
            tz=timezone,  # store only what the user explicitly passed
            enabled=True,
            next_run_at=next_run,
        )
        self._jobs = [j for j in self._jobs if j.id != job_id]  # upsert
        self._jobs.append(job)
        self._save()
        self._arm_timer()
        return job_id

    def remove_job(self, job_id: str) -> None:
        """Remove a job by id. Raises KeyError if not found."""
        before = len(self._jobs)
        self._jobs = [j for j in self._jobs if j.id != job_id]
        if len(self._jobs) == before:
            raise KeyError(f"Job {job_id!r} not found")
        self._save()
        self._arm_timer()

    def list_jobs(self) -> list[dict]:
        return [_job_to_dict(j) for j in self._jobs]

    async def run_job_now(self, job_id: str) -> None:
        """Fire a job immediately regardless of schedule. Works on disabled jobs."""
        job = next((j for j in self._jobs if j.id == job_id), None)
        if job is None:
            raise KeyError(f"Job {job_id!r} not found")
        await self._fire_job(job)
        self._save()
        # next_run_at intentionally NOT modified

    # ── internals ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        tmp = self._jobs_file.with_suffix(".json.tmp")
        if tmp.exists():
            tmp.unlink()
        if not self._jobs_file.exists():
            self._jobs = []
            return
        try:
            data = json.loads(self._jobs_file.read_text())
            self._jobs = [_job_from_dict(j) for j in data.get("jobs", [])]
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to load %s: %s — starting empty", self._jobs_file, exc)
            self._jobs = []

    def _save(self) -> None:
        self._jobs_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "jobs": [_job_to_dict(j) for j in self._jobs]}
        tmp = self._jobs_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self._jobs_file)

    def _recompute_next_runs(self) -> None:
        now = datetime.now(UTC)
        for job in self._jobs:
            if not job.enabled:
                continue
            if job.next_run_at is None or job.next_run_at <= now:
                resolved_tz = job.tz or self._timezone
                job.next_run_at = _compute_next_run(job.schedule, resolved_tz, now)

    def _arm_timer(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        if not self._running:
            return
        enabled_times = [j.next_run_at for j in self._jobs if j.enabled and j.next_run_at]
        if not enabled_times:
            return
        next_wake = min(enabled_times)
        delay = max(0.0, (next_wake - datetime.now(UTC)).total_seconds())
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # No event loop running (e.g. sync context / tests)
        self._timer_task = loop.create_task(self._tick(delay))

    async def _tick(self, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._on_timer()

    async def _on_timer(self) -> None:
        now = datetime.now(UTC)
        for job in self._jobs:
            if job.enabled and job.next_run_at and now >= job.next_run_at:
                # Advance next_run_at BEFORE firing (prevents double-fire on cancellation)
                resolved_tz = job.tz or self._timezone
                job.next_run_at = _compute_next_run(job.schedule, resolved_tz, now)
                await self._fire_job(job)
        try:
            self._save()
        except Exception as exc:
            logger.error("Failed to save jobs after timer tick: %s", exc)
        self._arm_timer()

    async def _fire_job(self, job: CronJob) -> None:
        now = datetime.now(UTC)
        reply = self._make_reply() if (self._send_fn and self._default_user_id) else noop_reply
        try:
            msg = Message(
                text=job.prompt,
                channel="cron",
                session_id=f"cron_{job.id}",
                user_id="cron",
                reply=reply,
            )
            await self._queue.put(msg)
            job.last_run_at = now
            job.last_status = "ok"
        except Exception as exc:
            logger.error("Failed to fire job %r: %s", job.id, exc)
            job.last_run_at = now
            job.last_status = "error"

    def _make_reply(self) -> Callable[[str], Awaitable[None]]:
        send_fn = self._send_fn
        user_id = self._default_user_id

        async def _reply(text: str) -> None:
            await send_fn(user_id, text)  # type: ignore[misc]

        return _reply
