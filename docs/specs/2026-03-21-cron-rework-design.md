# Cron System Rework — Design Spec

**Date:** 2026-03-21
**Status:** Approved

## Goal

Replace APScheduler + SQLite with a simpler, self-contained scheduler. `data/jobs.json` becomes the single authoritative store for all jobs (static and dynamic). Asyncio-native, write-through JSON persistence, no external scheduler framework.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Schedule types | Cron only (5-field) | Covers all real use cases |
| Authoritative store | `data/jobs.json` | Writable Docker volume; `config/jobs.json` is seed only |
| Scheduler | Custom asyncio timer | Removes APScheduler, no pickle hacks, trivially testable |
| State tracking | Definition + lightweight state | `next_run_at`, `last_run_at`, `last_status` |
| Timer strategy | Sleep-until-next-job | Exact timing; cancel+rearm on mutation |
| Missed windows | Skip (use `now` as base) | Fire once on recovery, not retroactively |
| Consolidation timer | Out of scope | Not yet wired (`# TODO` in main.py); will use plain `asyncio.create_task` when implemented |

---

## 1. JSON Schema

`data/jobs.json` is read on startup and written on every mutation (add, remove, post-execution state update).

**Seed behaviour:** If `data/jobs.json` does not exist, the scheduler copies `config/jobs.json` → `data/jobs.json` before loading. If `config/jobs.json` also doesn't exist, the store starts empty. Once `data/jobs.json` exists it is the sole source — `config/jobs.json` is never read again.

```json
{
  "version": 1,
  "jobs": [
    {
      "id": "daily_digest",
      "schedule": "0 8 * * *",
      "tz": "Europe/Paris",
      "prompt": "Generate the daily digest",
      "source": "telegram",
      "executor": "digest",
      "enabled": true,
      "next_run_at": "2026-03-22T08:00:00+00:00",
      "last_run_at": "2026-03-21T08:00:00+00:00",
      "last_status": "ok"
    }
  ]
}
```

**Field notes:**
- `tz` — optional IANA timezone string; falls back to `scheduler.timezone` from `config.json`
- `source` — where the job was created: `"telegram"` (agent tool) or `"ui"` (REST API or seed file)
- `enabled` — allows pausing a job without deleting it
- `next_run_at`, `last_run_at` — UTC ISO 8601 strings (`+00:00`); `null` if never run
- `last_status` — `"ok"` or `"error"`; `null` if never run

**Datetime handling:** All internal datetimes are UTC-aware (`datetime` with `timezone.utc`). `croniter` is always called with a UTC-aware base time. `next_run_at` is serialized as UTC ISO 8601. No naive datetimes anywhere in the scheduler.

---

## 2. Architecture

### Files changed

| File | Change |
|------|--------|
| `src/kore/scheduler/cron.py` | Complete rewrite (~160 lines) |
| `src/kore/config.py` | `SchedulerConfig`: remove `db_path`, rename `jobs_file` → `seed_file`, add `data_jobs_file: str = "data/jobs.json"` |
| `src/kore/tools/cron_tools.py` | `message` → `prompt`; add `source="telegram"`; `JobLookupError` → `KeyError` |
| `src/kore/gateway/routes_api.py` | `CreateJobRequest.message` → `prompt`; add `source="ui"`; `APJobLookupError` → `KeyError` |
| `src/kore/main.py` | Pass `jobs_file=KORE_HOME/config.scheduler.data_jobs_file`, `seed_file=KORE_HOME/config.scheduler.seed_file` instead of `db_path=` |
| `pyproject.toml` | Swap `apscheduler` for `croniter` |
| `tests/test_cron.py` | Rewrite without `SQLAlchemyJobStore` patch |
| `tests/test_cron_integration.py` | Rewrite with asyncio timer tests |
| `tests/test_cron_tools.py` | Rename `message` → `prompt` in calls |

### `CronJob` dataclass

```python
@dataclass
class CronJob:
    id: str
    schedule: str
    prompt: str
    source: str = "ui"                    # "telegram" | "ui"
    executor: str = "general"
    tz: str | None = None
    enabled: bool = True
    next_run_at: datetime | None = None   # UTC-aware
    last_run_at: datetime | None = None   # UTC-aware
    last_status: str | None = None        # "ok" | "error"
```

### `KoreCronScheduler` — public API

```python
def start() -> None
def stop() -> None
def init_sender(send_fn, user_id) -> None   # must be called before start()
def add_job(job_id, cron_expr, prompt, source, executor, timezone) -> str
def remove_job(job_id) -> None              # raises KeyError if not found
def list_jobs() -> list[dict]
async def run_job_now(job_id) -> None       # raises KeyError if not found
```

---

## 3. Timer Flow

### Startup sequence (in `start()`)

```
_maybe_seed()          → copy config/jobs.json → data/jobs.json if not present
_load()                → parse data/jobs.json into self._jobs
_recompute_next_runs() → for each enabled job (see algorithm below)
_save()                → atomic write of updated state
_arm_timer()           → schedule asyncio task
```

`init_sender()` must be called before `start()`. If a job fires without a configured sender, it falls back to `noop_reply` (job still runs, result discarded).

### `_recompute_next_runs()` algorithm

For each enabled job:
- If `next_run_at` is already in the **future** → leave it unchanged (preserves recently-added jobs)
- If `next_run_at` is in the **past or None** → recompute from `now` as the croniter base

This means a job whose scheduled window fell during downtime gets its next future occurrence (skip policy). A job added moments before a restart keeps its scheduled time.

### `_arm_timer()`

```
enabled_times = [j.next_run_at for j in self._jobs if j.enabled and j.next_run_at]
if not enabled_times → return  (rearms automatically on next add_job)
next_wake = min(enabled_times)
cancel existing timer task if any
delay = max(0.0, (next_wake - now_utc).total_seconds())
self._timer_task = asyncio.create_task(_tick(delay))
```

### `_on_timer()`

```
now = datetime.now(UTC)
for job in self._jobs where job.enabled and job.next_run_at and now >= job.next_run_at:
    await _fire_job(job)   → push Message(text=job.prompt, ...) to queue
    job.last_run_at = now
    job.last_status = "ok"   (or "error" if queue put raises)
    job.next_run_at = _compute_next_run(job.schedule, job.tz, after=now)
_save()
_arm_timer()
```

Multiple jobs overdue in the same tick all fire before saving and rearming.

### Mutations during sleep

`add_job` and `remove_job` both:
1. Update `self._jobs` in memory
2. Call `_save()` (atomic write)
3. Call `_arm_timer()` (cancels current sleep, recalculates)

### `run_job_now()`

Fires immediately regardless of schedule. Updates `last_run_at`, `last_status`, saves JSON — same state tracking as the timer path. Works on disabled jobs (explicit manual trigger). Does **not** affect `next_run_at`.

---

## 4. Persistence

All writes use an atomic pattern to prevent corruption:

```python
def _save(self) -> None:
    data = {"version": 1, "jobs": [_job_to_dict(j) for j in self._jobs]}
    tmp = self._jobs_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, self._jobs_file)
```

`os.replace()` is atomic on POSIX. On startup: if a stale `.json.tmp` exists, delete it silently and use the existing `.json`.

---

## 5. Error Handling

| Situation | Behaviour |
|-----------|-----------|
| Invalid cron expression at `add_job` | `croniter` raises `ValueError`; JSON not modified |
| Queue put fails during execution | `last_status = "error"` recorded; scheduler continues |
| Missing `data/jobs.json` | Seed from `config/jobs.json`; if also missing, start empty |
| Malformed `jobs.json` | `JSONDecodeError` logged as warning; start with empty store |
| Stale `.json.tmp` on startup | Delete silently; use existing `.json` |
| `remove_job` unknown id | Raises `KeyError` |
| Unknown timezone string | `ZoneInfoNotFoundError` raised at `add_job` time; JSON not modified |
| `start()` called before `init_sender()` | Jobs fire with `noop_reply`; no crash |

---

## 6. Dependency Changes

**Remove:** `apscheduler>=3.10,<4.0`

**Add:** `croniter>=2.0,<3.0` — lightweight cron expression parser. Used only in `_compute_next_run()`.

`zoneinfo` and `os` are stdlib (Python 3.12). No other new dependencies.

---

## 7. Testing Strategy

### `tests/test_cron.py` — unit tests (no async timer)

**Persistence & lifecycle**
- Scheduler seeds from `config/jobs.json` when `data/jobs.json` absent; seed jobs get `source="ui"`
- Scheduler loads existing `data/jobs.json` on start
- Stale `.json.tmp` cleaned up on startup
- `next_run_at` recomputed on startup: past/None → new future time; already-future → unchanged

**`add_job`**
- Writes new job to JSON immediately (atomic write)
- All fields present in JSON: `id`, `schedule`, `prompt`, `source`, `executor`, `tz`, `enabled`, `next_run_at`
- `add_job` with duplicate id replaces the existing job (upsert)
- Invalid cron expression raises `ValueError`, JSON unchanged
- Unknown timezone raises `ZoneInfoNotFoundError`, JSON unchanged

**`remove_job`**
- Removes job from JSON and in-memory list
- Raises `KeyError` for unknown id; JSON unchanged

**`list_jobs`**
- Returns correct fields: `id`, `schedule`, `prompt`, `source`, `executor`, `next_run_at`, `last_run_at`, `last_status`

**`run_job_now`**
- Pushes `Message` with `text=job.prompt`, `session_id=f"cron_{job.id}"`, `user_id="cron"`
- Updates `last_run_at` and `last_status="ok"` and saves JSON
- Does **not** modify `next_run_at`
- Works on disabled jobs
- Raises `KeyError` for unknown id

**Timer path**
- Disabled job skipped by `_on_timer`
- Empty job list: `_arm_timer` does nothing, no crash
- `_on_timer` with queue put error: `last_status="error"` recorded, scheduler continues (does not crash)

**Telegram delivery**
- When `init_sender` is configured and job fires via `run_job_now`, the `reply` callable calls `send_fn(user_id, text)`
- When `init_sender` is not configured, reply falls back to `noop_reply` (no crash)

### `tests/test_cron_integration.py` — async timer tests

- Single job fires and pushes `Message` to queue when due (monkeypatch `_compute_next_run` to return `now + 0.05s`)
- `last_run_at`, `last_status="ok"`, and `next_run_at` written to JSON after execution
- Multiple overdue jobs in the same tick all fire before `_save()`/`_arm_timer()` is called
- Adding a job mid-sleep rearms timer; new job fires at correct time

### `tests/test_cron_tools.py`

- `cron_create` calls `add_job` with `source="telegram"` and returns confirmation string
- `cron_list` returns formatted job list
- `cron_delete` calls `remove_job` and returns confirmation string
- `cron_delete` with non-existent id returns error string (does not raise)
- `prompt` used consistently (not `message`) in all tool signatures and return values
