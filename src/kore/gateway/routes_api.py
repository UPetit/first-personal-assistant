from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ── /api/jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def get_jobs(request: Request) -> list[dict[str, Any]]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        return []
    return scheduler.list_jobs()


class CreateJobRequest(BaseModel):
    job_id: str
    schedule: str
    prompt: str
    timezone: str | None = None


@router.post("/jobs", status_code=201)
async def create_job(body: CreateJobRequest, request: Request) -> dict[str, str]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        scheduler.add_job(
            body.job_id, body.schedule, body.prompt,
            source="ui", timezone=body.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created", "job_id": body.job_id}


@router.post("/jobs/{job_id}/run")
async def run_job_now(
    job_id: str,
    request: Request,
) -> dict[str, str]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        await scheduler.run_job_now(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "triggered", "job_id": job_id}


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
) -> dict[str, str]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        scheduler.remove_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "job_id": job_id}


# ── /api/agents ───────────────────────────────────────────────────────────────

@router.get("/agents")
async def get_agents(request: Request) -> dict[str, Any]:
    """Return the v2 primary agent + subagent configuration.

    v2 replaced planner/executors with a single primary agent plus a dict of
    narrow subagents (deep_research, draft_longform) delegated to via tool calls.
    """
    config = request.app.state.config
    primary = None
    if config.agents is not None and config.agents.primary is not None:
        primary = {
            "model": config.agents.primary.model,
            "tools": config.agents.primary.tools,
            "skills": config.agents.primary.skills,
        }
    subagents = {}
    if config.agents is not None:
        subagents = {
            name: {
                "model": sub.model,
                "tools": sub.tools,
                "skills": sub.skills,
            }
            for name, sub in config.agents.subagents.items()
        }
    return {"primary": primary, "subagents": subagents}


# ── /api/skills ───────────────────────────────────────────────────────────────

@router.get("/skills")
async def get_skills(request: Request) -> dict[str, Any]:
    registry = request.app.state.skill_registry
    if registry is None:
        return {"builtin": [], "user": []}

    registry.reload()

    builtin: list[dict] = []
    user: list[dict] = []

    for skill in registry.all_skills():
        missing = [
            b for b in skill.required_bins if not shutil.which(b)
        ] + [
            e for e in skill.required_env if not os.environ.get(e)
        ]
        info: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "emoji": skill.emoji,
            "always_on": skill.always_on,
            "required_tools": skill.required_tools,
            "required_bins": skill.required_bins,
            "required_env": skill.required_env,
            "active": len(missing) == 0,
            "missing": missing,
        }
        if skill.path.is_relative_to(registry.user_dir):
            user.append(info)
        else:
            builtin.append(info)

    return {"builtin": builtin, "user": user}


# ── /api/memory ───────────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory(request: Request) -> dict[str, Any]:
    cm = request.app.state.core_memory
    return cm.get() if cm is not None else {}


class UpdateMemoryRequest(BaseModel):
    path: str
    value: Any


@router.put("/memory")
async def update_memory(
    body: UpdateMemoryRequest,
    request: Request,
) -> dict[str, str]:
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    request_id = uuid4().hex[:8]
    try:
        cm.update(body.path, body.value)
    except Exception:
        logger.exception("update_memory error", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"detail": "Operation failed", "request_id": request_id},
        )
    return {"status": "updated", "path": body.path}


@router.delete("/memory/{path:path}")
async def delete_memory(
    path: str,
    request: Request,
) -> dict[str, str]:
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    request_id = uuid4().hex[:8]
    try:
        cm.delete(path)
    except Exception:
        logger.exception("delete_memory error", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"detail": "Operation failed", "request_id": request_id},
        )
    return {"status": "deleted", "path": path}


# ── /api/logs ─────────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    request: Request,
    n: int = Query(default=100, ge=1, le=1000),
) -> list[str]:
    return request.app.state.log_handler.recent(n)


# ── /api/sessions ─────────────────────────────────────────────────────────────

@router.get("/sessions")
async def get_sessions() -> list[dict[str, Any]]:
    """List all sessions sorted newest-first.

    Reads from ~/.kore/workspace/sessions/*.json via SessionBuffer's _sessions_dir().
    Returns [] if the directory does not exist (fresh install, no sessions yet).
    """
    from kore.session.buffer import _sessions_dir

    sess_dir = _sessions_dir()
    if not sess_dir.exists():
        return []

    sessions = []
    for path in sess_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            turns = data.get("turns", [])
            user_turns = [t for t in turns if t.get("role") == "user"]
            last_message = (user_turns[-1]["content"][:100] if user_turns else "")
            sessions.append({
                "session_id": data["session_id"],
                "created_at": data["created_at"],
                "turn_count": len(turns) // 2,
                "last_message": last_message,
            })
        except Exception:
            logger.warning("Skipping corrupt session file: %s", path)

    sessions.sort(key=lambda s: s["created_at"], reverse=True)
    return sessions


@router.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str, request: Request) -> list[dict[str, Any]]:
    """Return all persisted trace events for a session, ordered by insertion.

    Returns an empty list when session tracing is disabled (trace_store is None).
    """
    trace_store = request.app.state.trace_store
    if trace_store is None:
        return []
    return await trace_store.get_session(session_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Return full session content by session_id. Returns 404 if not found."""
    from kore.session.buffer import _sessions_dir

    path = _sessions_dir() / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to read session file") from exc


# ── /api/message ──────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    text: str
    session_id: str = "api_default"


class MessageResponse(BaseModel):
    response: str
    session_id: str


@router.post("/message", response_model=MessageResponse)
async def post_message(
    body: MessageRequest,
    request: Request,
) -> MessageResponse:
    orchestrator = request.app.state.orchestrator
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available")
    request_id = uuid4().hex[:8]
    try:
        response = await orchestrator.run(body.text, body.session_id)
    except Exception:
        logger.exception("post_message error", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"detail": "Operation failed", "request_id": request_id},
        )
    return MessageResponse(response=response.content, session_id=body.session_id)
