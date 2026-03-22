# Phase 6 — Web UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI gateway (REST API + WebSocket log streaming + Telegram webhook) and a React/Vite dashboard served as static files, enabling browser-based monitoring and control of the Kore assistant.

**Architecture:** The FastAPI app is created by a factory function (`create_app`) that accepts pre-built component instances via parameters and stores them in `app.state`. All `/api/*` routes are protected by HTTP Basic auth with per-user rate limiting. The React frontend is a Vite SPA built to `src/kore/ui/static/` and served by FastAPI's `StaticFiles`. In development, Vite proxies `/api` and `/ws` to the running backend.

**Tech Stack:** FastAPI ≥ 0.110, uvicorn[standard] ≥ 0.29, python-multipart ≥ 0.0.9, httpx (already present for tests), React 18, Vite 5, react-router-dom 6

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/kore/gateway/server.py` | Create | FastAPI app factory, lifespan, state injection, static files |
| `src/kore/gateway/auth.py` | Create | HTTP Basic auth dependency + sliding-window rate limiter |
| `src/kore/gateway/log_handler.py` | Create | `WebSocketLogHandler` — per-listener queues + ring buffer |
| `src/kore/gateway/routes_api.py` | Create | All `/api/*` REST endpoints |
| `src/kore/gateway/routes_ws.py` | Create | `/ws/logs` WebSocket endpoint |
| `src/kore/gateway/routes_webhook.py` | Create | `/telegram/webhook` POST endpoint |
| `src/kore/ui/static/.gitkeep` | Create | Placeholder so FastAPI static dir exists before React build |
| `src/kore/main.py` | Modify | Add uvicorn server + orchestrator injection to `create_app` |
| `pyproject.toml` | Modify | Add fastapi, uvicorn[standard], python-multipart |
| `tests/test_gateway.py` | Create | All route tests, auth tests, rate limit, WebSocket lifecycle |
| `ui/package.json` | Create | React + Vite deps |
| `ui/vite.config.js` | Create | Build output to `src/kore/ui/static/`, dev proxy to :8000 |
| `ui/index.html` | Create | Vite HTML entry point |
| `ui/src/App.jsx` | Create | React Router layout + navigation |
| `ui/src/pages/Overview.jsx` | Create | Status + recent logs panel |
| `ui/src/pages/Logs.jsx` | Create | Live WebSocket log stream |
| `ui/src/pages/Jobs.jsx` | Create | List/create/delete CRON jobs |
| `ui/src/pages/Agents.jsx` | Create | List executors + planner config |
| `ui/src/pages/Memory.jsx` | Create | View/edit core memory |
| `ui/src/pages/Settings.jsx` | Create | Read-only config display |

---

## Task 1: Dependencies + FastAPI Foundation

**Files:**
- Modify: `pyproject.toml`
- Create: `src/kore/gateway/log_handler.py`
- Create: `src/kore/gateway/auth.py`
- Create: `src/kore/gateway/server.py`
- Create: `src/kore/ui/static/.gitkeep`

---

- [ ] **Step 1: Write failing tests for auth and log_handler**

Create `tests/test_gateway.py` with just the foundation tests:

```python
from __future__ import annotations

import asyncio
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from starlette.testclient import TestClient
from unittest.mock import MagicMock

from kore.config import KoreConfig, SecurityConfig, UIConfig, AgentsConfig


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_config(
    auth_enabled: bool = True,
    username: str = "admin",
    password: str = "secret",
) -> KoreConfig:
    from kore.config import LLMConfig
    return KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={}),
        security=SecurityConfig(
            api_auth_enabled=auth_enabled,
            api_username=username,
            api_password=SecretStr(password) if password else None,
        ),
    )


def _make_app(config: KoreConfig | None = None, **kwargs):
    from kore.gateway.server import create_app
    return create_app(config or _make_config(), **kwargs)


# ── log_handler ───────────────────────────────────────────────────────────────

def test_log_handler_emit_buffers_message():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello world", (), None)
    handler.emit(record)
    assert any("hello world" in entry for entry in handler.recent(10))


def test_log_handler_listener_receives_emitted_message():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    q = handler.add_listener()
    record = logging.LogRecord("test", logging.INFO, "", 0, "broadcast me", (), None)
    handler.emit(record)
    assert not q.empty()
    msg = q.get_nowait()
    assert "broadcast me" in msg


def test_log_handler_remove_listener_stops_delivery():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    q = handler.add_listener()
    handler.remove_listener(q)
    record = logging.LogRecord("test", logging.INFO, "", 0, "gone", (), None)
    handler.emit(record)
    assert q.empty()


def test_log_handler_recent_returns_last_n():
    from kore.gateway.log_handler import WebSocketLogHandler
    handler = WebSocketLogHandler()
    for i in range(5):
        record = logging.LogRecord("t", logging.INFO, "", 0, f"msg {i}", (), None)
        handler.emit(record)
    recent = handler.recent(3)
    assert len(recent) == 3
    assert "msg 4" in recent[-1]


# ── auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_no_credentials_returns_401():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/memory")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_valid_credentials_accepted():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/memory", auth=("admin", "secret"))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_wrong_password_rejected():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/memory", auth=("admin", "wrong"))
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_disabled_allows_all():
    app = _make_app(_make_config(auth_enabled=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/memory")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429():
    config = _make_config()
    config = config.model_copy(update={"security": SecurityConfig(
        api_auth_enabled=True,
        api_username="admin",
        api_password=SecretStr("secret"),
        rate_limit_per_user=2,
    )})
    app = _make_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/api/memory", auth=("admin", "secret"))
        r2 = await c.get("/api/memory", auth=("admin", "secret"))
        r3 = await c.get("/api/memory", auth=("admin", "secret"))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -v 2>&1 | head -20
```

Expected: `ImportError` (modules don't exist yet)

- [ ] **Step 3: Add dependencies to pyproject.toml**

In the `[project]` → `dependencies` list, add:

```toml
"fastapi>=0.110",
"uvicorn[standard]>=0.29",
"python-multipart>=0.0.9",
```

Install: `cd /root/kore-ai && pip install -e ".[dev]" -q`

- [ ] **Step 4: Create `src/kore/gateway/log_handler.py`**

```python
from __future__ import annotations

import asyncio
import logging
from collections import deque


class WebSocketLogHandler(logging.Handler):
    """Logging handler that broadcasts formatted records to all WebSocket listeners.

    - ``add_listener()`` returns a per-connection ``asyncio.Queue``.
    - ``recent(n)`` returns the last *n* buffered entries for late-joining clients.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=maxsize)
        self._listeners: set[asyncio.Queue[str]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self._buffer.append(msg)
        for q in list(self._listeners):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def add_listener(self, maxsize: int = 500) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._listeners.add(q)
        return q

    def remove_listener(self, q: asyncio.Queue[str]) -> None:
        self._listeners.discard(q)

    def recent(self, n: int = 100) -> list[str]:
        """Return last *n* buffered log entries."""
        entries = list(self._buffer)
        return entries[-n:]
```

- [ ] **Step 5: Create `src/kore/gateway/auth.py`**

```python
from __future__ import annotations

import secrets
from collections import defaultdict
from time import monotonic
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

if TYPE_CHECKING:
    pass

security = HTTPBasic(auto_error=False)

# Sliding-window rate limiter state (in-memory; resets on restart — acceptable for v1)
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 60.0


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    """FastAPI dependency — validates HTTP Basic credentials and enforces rate limit.

    Returns the authenticated username (or "anonymous" when auth is disabled).
    """
    cfg = request.app.state.config.security

    if not cfg.api_auth_enabled:
        return "anonymous"

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    expected_password = (
        cfg.api_password.get_secret_value() if cfg.api_password else ""
    )
    valid_user = secrets.compare_digest(
        credentials.username.encode(), cfg.api_username.encode()
    )
    valid_pass = secrets.compare_digest(
        credentials.password.encode(), expected_password.encode()
    )
    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Sliding-window rate limit
    now = monotonic()
    bucket = [t for t in _rate_buckets[credentials.username] if now - t < _WINDOW_SECONDS]
    if len(bucket) >= cfg.rate_limit_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {cfg.rate_limit_per_user} requests per minute",
        )
    bucket.append(now)
    _rate_buckets[credentials.username] = bucket

    return credentials.username
```

- [ ] **Step 6: Create `src/kore/gateway/server.py`**

```python
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from kore.gateway.log_handler import WebSocketLogHandler

if TYPE_CHECKING:
    from kore.agents.orchestrator import Orchestrator
    from kore.channels.telegram import TelegramChannel
    from kore.config import KoreConfig
    from kore.gateway.queue import MessageQueue
    from kore.memory.core_memory import CoreMemory
    from kore.scheduler.cron import KoreCronScheduler

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "ui" / "static"


def create_app(
    config: KoreConfig,
    *,
    queue: MessageQueue | None = None,
    scheduler: KoreCronScheduler | None = None,
    core_memory: CoreMemory | None = None,
    orchestrator: Orchestrator | None = None,
    telegram_channel: TelegramChannel | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    All Kore components are injected via parameters and stored in ``app.state``
    so routes can access them without global imports.
    """
    log_handler = WebSocketLogHandler()

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN001
        logging.getLogger().addHandler(log_handler)
        logger.info("Kore gateway started.")
        yield
        logging.getLogger().removeHandler(log_handler)

    app = FastAPI(title="Kore AI Gateway", lifespan=lifespan)

    # Inject shared state
    app.state.config = config
    app.state.queue = queue
    app.state.scheduler = scheduler
    app.state.core_memory = core_memory
    app.state.orchestrator = orchestrator
    app.state.telegram_channel = telegram_channel
    app.state.log_handler = log_handler

    # Register routers (imported here to keep create_app importable without side-effects)
    from kore.gateway.routes_api import router as api_router
    from kore.gateway.routes_webhook import router as webhook_router
    from kore.gateway.routes_ws import router as ws_router

    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)
    app.include_router(webhook_router)

    # Serve built React frontend if present
    if _STATIC_DIR.exists() and any(_STATIC_DIR.iterdir()):
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="ui")

    return app
```

- [ ] **Step 7: Create `src/kore/ui/static/.gitkeep`**

Create empty file so the directory exists in the repo.

- [ ] **Step 8: Create stub routers** (to unblock tests)

Create empty router stubs so `server.py` can import them:

`src/kore/gateway/routes_api.py`:
```python
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from kore.gateway.auth import require_auth

router = APIRouter()

@router.get("/memory")
async def get_memory(request: Request, _: str = Depends(require_auth)) -> dict:
    cm = request.app.state.core_memory
    return cm.get() if cm is not None else {}
```

`src/kore/gateway/routes_ws.py`:
```python
from __future__ import annotations
from fastapi import APIRouter
router = APIRouter()
```

`src/kore/gateway/routes_webhook.py`:
```python
from __future__ import annotations
from fastapi import APIRouter
router = APIRouter()
```

- [ ] **Step 9: Run tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -v
```

Expected: 9 foundation tests pass (log_handler + auth tests)

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/kore/gateway/ src/kore/ui/static/.gitkeep tests/test_gateway.py
git commit -m "feat: FastAPI foundation — server factory, auth, log handler"
```

---

## Task 2: REST API Routes

**Files:**
- Modify: `src/kore/gateway/routes_api.py` (replace stub with full implementation)
- Modify: `tests/test_gateway.py` (add API route tests)

---

- [ ] **Step 1: Add REST route tests to `tests/test_gateway.py`**

Append after the existing auth tests:

```python
# ── REST routes ───────────────────────────────────────────────────────────────

def _make_app_with_components(**kwargs):
    """Build app with mock components pre-wired."""
    from unittest.mock import MagicMock
    from kore.config import ExecutorConfig, AgentsConfig

    config = _make_config()
    # Give it a planner + general executor so /api/agents has something to return
    config = config.model_copy(update={"agents": AgentsConfig(
        planner=None,
        executors={
            "general": ExecutorConfig(
                model="anthropic:claude-sonnet-4-6",
                prompt_file="general.md",
                tools=["web_search"],
                description="General executor",
            )
        },
    )})

    core_memory = MagicMock()
    core_memory.get.return_value = {"user": {"name": "Alice"}}

    scheduler = MagicMock()
    scheduler.list_jobs.return_value = [
        {"id": "daily_digest", "next_run": "2026-03-18 08:00:00"}
    ]

    return _make_app(config, core_memory=core_memory, scheduler=scheduler, **kwargs)


@pytest.mark.asyncio
async def test_get_jobs_returns_list():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/jobs", auth=("admin", "secret"))
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["id"] == "daily_digest"


@pytest.mark.asyncio
async def test_post_job_creates_job():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/jobs", json={
            "job_id": "new_job",
            "schedule": "0 9 * * *",
            "message": "Do the thing",
        }, auth=("admin", "secret"))
    assert r.status_code == 200
    app.state.scheduler.add_job.assert_called_once_with(
        "new_job", "0 9 * * *", "Do the thing", channel="cron", executor="general"
    )


@pytest.mark.asyncio
async def test_delete_job_removes_it():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/jobs/daily_digest", auth=("admin", "secret"))
    assert r.status_code == 200
    app.state.scheduler.remove_job.assert_called_once_with("daily_digest")


@pytest.mark.asyncio
async def test_get_agents_returns_executor_list():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/agents", auth=("admin", "secret"))
    assert r.status_code == 200
    data = r.json()
    assert "general" in data["executors"]
    assert data["executors"]["general"]["model"] == "anthropic:claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_get_memory_returns_dict():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/memory", auth=("admin", "secret"))
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_put_memory_updates_path():
    from unittest.mock import MagicMock
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put("/api/memory", json={"path": "user.name", "value": "Bob"},
                        auth=("admin", "secret"))
    assert r.status_code == 200
    app.state.core_memory.update.assert_called_once_with("user.name", "Bob")


@pytest.mark.asyncio
async def test_delete_memory_path():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/memory/user.name", auth=("admin", "secret"))
    assert r.status_code == 200
    app.state.core_memory.delete.assert_called_once_with("user.name")


@pytest.mark.asyncio
async def test_get_logs_returns_recent_entries():
    from kore.gateway.log_handler import WebSocketLogHandler
    import logging
    app = _make_app_with_components()
    # Emit a log so the handler buffer has something
    record = logging.LogRecord("kore", logging.INFO, "", 0, "startup complete", (), None)
    app.state.log_handler.emit(record)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=10", auth=("admin", "secret"))
    assert r.status_code == 200
    entries = r.json()
    assert isinstance(entries, list)
    assert any("startup complete" in e for e in entries)


@pytest.mark.asyncio
async def test_post_message_calls_orchestrator():
    from unittest.mock import AsyncMock
    from kore.llm.types import AgentResponse

    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(return_value=AgentResponse(
        content="Hello back!", tool_calls=[], model_used="test"
    ))
    app = _make_app_with_components(orchestrator=mock_orch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "Hello", "session_id": "api_test"},
                         auth=("admin", "secret"))
    assert r.status_code == 200
    assert r.json()["response"] == "Hello back!"
    mock_orch.run.assert_called_once_with("Hello", "api_test")


@pytest.mark.asyncio
async def test_post_message_503_when_no_orchestrator():
    app = _make_app_with_components(orchestrator=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "Hi"}, auth=("admin", "secret"))
    assert r.status_code == 503
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "job or agent or memory or log or message" -v 2>&1 | head -30
```

Expected: failures (routes not implemented yet)

- [ ] **Step 3: Implement `src/kore/gateway/routes_api.py`**

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from kore.gateway.auth import require_auth

router = APIRouter()


# ── /api/jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs")
async def get_jobs(request: Request, _: str = Depends(require_auth)) -> list[dict[str, str]]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        return []
    return scheduler.list_jobs()


class CreateJobRequest(BaseModel):
    job_id: str
    schedule: str
    message: str
    channel: str = "cron"
    executor: str = "general"


@router.post("/jobs")
async def create_job(
    body: CreateJobRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        scheduler.add_job(
            body.job_id, body.schedule, body.message,
            channel=body.channel, executor=body.executor,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created", "job_id": body.job_id}


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    scheduler = request.app.state.scheduler
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    try:
        scheduler.remove_job(job_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "job_id": job_id}


# ── /api/agents ───────────────────────────────────────────────────────────────

@router.get("/agents")
async def get_agents(request: Request, _: str = Depends(require_auth)) -> dict[str, Any]:
    config = request.app.state.config
    planner = None
    if config.agents.planner is not None:
        planner = {
            "model": config.agents.planner.model,
            "description": config.agents.planner.description,
        }
    executors = {
        name: {
            "model": exc.model,
            "description": exc.description,
            "tools": exc.tools,
        }
        for name, exc in config.agents.executors.items()
    }
    return {"planner": planner, "executors": executors}


# ── /api/memory ───────────────────────────────────────────────────────────────

@router.get("/memory")
async def get_memory(request: Request, _: str = Depends(require_auth)) -> dict[str, Any]:
    cm = request.app.state.core_memory
    return cm.get() if cm is not None else {}


class UpdateMemoryRequest(BaseModel):
    path: str
    value: Any


@router.put("/memory")
async def update_memory(
    body: UpdateMemoryRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    try:
        cm.update(body.path, body.value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "updated", "path": body.path}


@router.delete("/memory/{path:path}")
async def delete_memory(
    path: str,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    cm.delete(path)
    return {"status": "deleted", "path": path}


# ── /api/logs ─────────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    request: Request,
    n: int = 100,
    _: str = Depends(require_auth),
) -> list[str]:
    return request.app.state.log_handler.recent(n)


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
    _: str = Depends(require_auth),
) -> MessageResponse:
    orchestrator = request.app.state.orchestrator
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available")
    try:
        response = await orchestrator.run(body.text, body.session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MessageResponse(response=response.content, session_id=body.session_id)
```

- [ ] **Step 4: Run tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -v
```

Expected: all REST API tests pass (19+ tests)

- [ ] **Step 5: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add src/kore/gateway/routes_api.py tests/test_gateway.py
git commit -m "feat: REST API routes — jobs, agents, memory, logs, message"
```

---

## Task 3: WebSocket Log Streaming

**Files:**
- Modify: `src/kore/gateway/routes_ws.py` (replace stub)
- Modify: `tests/test_gateway.py` (add WebSocket tests)

---

- [ ] **Step 1: Add WebSocket tests**

Append to `tests/test_gateway.py`:

```python
# ── WebSocket ─────────────────────────────────────────────────────────────────

def test_ws_logs_accepts_connection():
    """TestClient (sync) supports WebSocket testing via starlette."""
    app = _make_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/logs") as ws:
        # connection accepted — no exception means success
        pass


def test_ws_logs_receives_emitted_log():
    """Log emitted after connect is delivered to the WebSocket client.

    Uses raise_server_exceptions=False so a timeout in receive_text doesn't
    surface as an unhandled exception — the assertion will simply fail if the
    message is not received within 2 s.
    """
    import logging
    import time
    app = _make_app()
    client = TestClient(app, raise_server_exceptions=False)
    with client.websocket_connect("/ws/logs") as ws:
        # Give the WebSocket handler a moment to reach the await queue.get() call
        time.sleep(0.05)
        record = logging.LogRecord("kore", logging.INFO, "", 0, "ws test log", (), None)
        app.state.log_handler.emit(record)
        data = ws.receive_text(timeout=2.0)
    assert "ws test log" in data


def test_ws_logs_disconnect_removes_listener():
    """After disconnect, the listener queue is removed from the handler.

    Checks listener count inside and outside the with block to verify cleanup.
    """
    import time
    app = _make_app()
    client = TestClient(app)
    before = len(app.state.log_handler._listeners)
    with client.websocket_connect("/ws/logs"):
        time.sleep(0.05)  # let handler reach await queue.get()
        during = len(app.state.log_handler._listeners)
    # Allow a moment for the finally block to execute
    time.sleep(0.05)
    after = len(app.state.log_handler._listeners)
    assert during == before + 1
    assert after == before
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "ws" -v
```

- [ ] **Step 3: Implement `src/kore/gateway/routes_ws.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket) -> None:
    """Stream log entries to connected clients in real time.

    Each connection gets its own asyncio.Queue registered in WebSocketLogHandler.
    Disconnecting (or any send failure) cleans up the listener automatically.
    """
    await websocket.accept()
    log_handler = websocket.app.state.log_handler
    queue = log_handler.add_listener()
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        log_handler.remove_listener(queue)
```

- [ ] **Step 4: Run tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "ws" -v
```

Expected: 3 WebSocket tests pass

- [ ] **Step 5: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add src/kore/gateway/routes_ws.py tests/test_gateway.py
git commit -m "feat: WebSocket /ws/logs endpoint with per-listener queue fanout"
```

---

## Task 4: Telegram Webhook Route

**Files:**
- Modify: `src/kore/gateway/routes_webhook.py` (replace stub)
- Modify: `tests/test_gateway.py` (add webhook tests)

---

- [ ] **Step 1: Add webhook tests**

Append to `tests/test_gateway.py`:

```python
# ── Telegram webhook ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telegram_webhook_calls_process_update():
    from unittest.mock import AsyncMock, MagicMock, patch
    from pydantic import SecretStr

    mock_channel = MagicMock()
    mock_channel.process_update = AsyncMock()

    app = _make_app(telegram_channel=mock_channel)
    payload = {"update_id": 1, "message": {"text": "hello"}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/telegram/webhook", json=payload)
    assert r.status_code == 200
    mock_channel.process_update.assert_called_once_with(payload)


@pytest.mark.asyncio
async def test_telegram_webhook_503_without_channel():
    app = _make_app()  # no telegram_channel
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 503
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "webhook" -v
```

- [ ] **Step 3: Implement `src/kore/gateway/routes_webhook.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram webhook POST and hand it to the TelegramChannel adapter."""
    channel = request.app.state.telegram_channel
    if channel is None:
        return Response(content="Telegram channel not configured", status_code=503)
    data = await request.json()
    await channel.process_update(data)
    return Response(status_code=200)
```

- [ ] **Step 4: Run tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -v
```

Expected: all gateway tests pass

- [ ] **Step 5: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add src/kore/gateway/routes_webhook.py tests/test_gateway.py
git commit -m "feat: Telegram webhook route — delegates to TelegramChannel.process_update"
```

---

## Task 5: Update main.py to Integrate FastAPI

**Files:**
- Modify: `src/kore/main.py`

---

The current `main.py` runs only the async consumer loop. Phase 6 adds the FastAPI HTTP server (uvicorn) running concurrently via `asyncio.gather`. The orchestrator is injected into `app.state` so REST clients can call `/api/message` directly.

**Design note — two orchestrator paths:** `app.state.orchestrator` receives the raw `Orchestrator` instance (with `run(text, session_id) → AgentResponse`). The queue consumer uses `_OrchestratorAdapter` which wraps the raw orchestrator and maps `Message → (text, session_id)`. REST callers bypass the queue and adapter entirely, calling the orchestrator directly. This is intentional: the queue path is for fire-and-forget channels (Telegram, CRON) while the REST path is synchronous request–response.

- [ ] **Step 1: Read `src/kore/main.py` in full** (already read above — 123 lines)

- [ ] **Step 2: Write integration test**

Append to `tests/test_cron_integration.py` (or `tests/test_gateway.py`):

```python
# In tests/test_gateway.py, append:

@pytest.mark.asyncio
async def test_create_app_with_orchestrator_state():
    """Verify orchestrator is accessible from app.state after create_app."""
    from unittest.mock import MagicMock
    mock_orch = MagicMock()
    app = _make_app(orchestrator=mock_orch)
    assert app.state.orchestrator is mock_orch
```

- [ ] **Step 3: Run to confirm it passes** (should already, since create_app sets state)

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py::test_create_app_with_orchestrator_state -v
```

- [ ] **Step 4: Update `src/kore/main.py`**

Replace the `main()` function (keep `_consume`, `_OrchestratorAdapter`, `_cli_main`, and `__main__` block intact). The new `main()`:

```python
async def main() -> None:
    config = load_config()
    queue = MessageQueue()

    # Build channel(s)
    channels: list[Channel] = []
    telegram_channel = None
    if config.channels.telegram is not None:
        telegram_channel = TelegramChannel(config.channels.telegram)
        channels.append(telegram_channel)
        await telegram_channel.start(queue)

    # Build scheduler
    db_path = KORE_HOME / config.scheduler.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    scheduler = KoreCronScheduler(
        db_path=db_path,
        queue=queue,
        timezone=config.scheduler.timezone,
    )
    cron_tools.init(scheduler)
    # start() must come before load_static_jobs() — APScheduler requires a running
    # event loop to register jobs with the SQLAlchemy job store.
    scheduler.start()
    scheduler.load_static_jobs(KORE_HOME / config.scheduler.jobs_file)

    # Build orchestrator
    raw_orchestrator = Orchestrator(config)
    orchestrator = _OrchestratorAdapter(raw_orchestrator)

    # TODO: wire consolidation timer

    # Build FastAPI app (orchestrator accessible for /api/message)
    from kore.gateway.server import create_app
    app = create_app(
        config,
        queue=queue,
        scheduler=scheduler,
        orchestrator=raw_orchestrator,
        telegram_channel=telegram_channel,
    )

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    async def _shutdown_watcher() -> None:
        await stop_event.wait()
        uvicorn_server.should_exit = True

    import uvicorn
    uvicorn_config = uvicorn.Config(
        app,
        host=config.ui.host,
        port=config.ui.port,
        log_config=None,  # use Kore's logging config
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)
    uvicorn_server.install_signal_handlers = lambda: None  # we handle signals ourselves

    logger.info("Kore is running on http://%s:%d", config.ui.host, config.ui.port)

    await asyncio.gather(
        uvicorn_server.serve(),
        _consume(queue, orchestrator),
        _shutdown_watcher(),
    )

    # Graceful teardown
    scheduler.stop()
    for ch in channels:
        await ch.stop()
    logger.info("Kore stopped.")
```

Also add `import uvicorn` at the top of the file (or keep the inline import inside `main()`).

- [ ] **Step 5: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

Expected: all tests still pass (main.py changes don't affect tests directly)

- [ ] **Step 6: Commit**

```bash
git add src/kore/main.py tests/test_gateway.py
git commit -m "feat: main.py — uvicorn + FastAPI gateway integrated with consumer loop"
```

---

## Task 6: React Frontend

**Files:**
- Create: `ui/package.json`
- Create: `ui/vite.config.js`
- Create: `ui/index.html`
- Create: `ui/src/App.jsx`
- Create: `ui/src/pages/Overview.jsx`
- Create: `ui/src/pages/Logs.jsx`
- Create: `ui/src/pages/Jobs.jsx`
- Create: `ui/src/pages/Agents.jsx`
- Create: `ui/src/pages/Memory.jsx`
- Create: `ui/src/pages/Settings.jsx`

**Note:** React frontend has no automated tests (tested manually in browser). The test step is a build verification.

---

- [ ] **Step 1: Create `ui/package.json`**

```json
{
  "name": "kore-ui",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.22.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.0",
    "vite": "^5.1.0"
  }
}
```

- [ ] **Step 2: Create `ui/vite.config.js`**

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/kore/ui/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
```

- [ ] **Step 3: Create `ui/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Kore AI</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Create `ui/src/main.jsx`**

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 5: Create `ui/src/App.jsx`**

```jsx
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import Overview from './pages/Overview.jsx'
import Logs from './pages/Logs.jsx'
import Jobs from './pages/Jobs.jsx'
import Agents from './pages/Agents.jsx'
import Memory from './pages/Memory.jsx'
import Settings from './pages/Settings.jsx'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/logs', label: 'Logs' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/agents', label: 'Agents' },
  { to: '/memory', label: 'Memory' },
  { to: '/settings', label: 'Settings' },
]

// TODO: Replace hardcoded credentials with a login prompt storing token in sessionStorage.
// For v1 personal use only — do NOT expose this build on a public network.
const AUTH = btoa('admin:secret')
export const headers = () => ({ Authorization: `Basic ${AUTH}`, 'Content-Type': 'application/json' })

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ display: 'flex', gap: '1rem', padding: '0.5rem 1rem', background: '#1a1a2e', color: '#eee' }}>
        <strong style={{ marginRight: '1rem' }}>Kore AI</strong>
        {NAV.map(({ to, label }) => (
          <NavLink key={to} to={to} end={to === '/'} style={({ isActive }) => ({ color: isActive ? '#90caf9' : '#ccc', textDecoration: 'none' })}>
            {label}
          </NavLink>
        ))}
      </nav>
      <main style={{ padding: '1rem' }}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
```

- [ ] **Step 6: Create `ui/src/pages/Overview.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { headers } from '../App.jsx'

export default function Overview() {
  const [logs, setLogs] = useState([])
  const [jobs, setJobs] = useState([])

  useEffect(() => {
    fetch('/api/logs?n=20', { headers: headers() }).then(r => r.json()).then(setLogs)
    fetch('/api/jobs', { headers: headers() }).then(r => r.json()).then(setJobs)
  }, [])

  return (
    <div>
      <h2>Overview</h2>
      <h3>Scheduled Jobs ({jobs.length})</h3>
      {jobs.length === 0 ? <p>No jobs scheduled.</p> : (
        <ul>{jobs.map(j => <li key={j.id}>{j.id} — next: {j.next_run}</li>)}</ul>
      )}
      <h3>Recent Logs</h3>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem', maxHeight: '300px', overflow: 'auto' }}>
        {logs.slice().reverse().join('\n') || '(no logs yet)'}
      </pre>
    </div>
  )
}
```

- [ ] **Step 7: Create `ui/src/pages/Logs.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'

export default function Logs() {
  const [lines, setLines] = useState([])
  const bottomRef = useRef(null)

  useEffect(() => {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${location.host}/ws/logs`)
    ws.onmessage = e => setLines(prev => [...prev.slice(-499), e.data])
    return () => ws.close()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div>
      <h2>Live Logs</h2>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem', height: '70vh', overflow: 'auto', fontSize: '0.8rem' }}>
        {lines.join('\n') || 'Waiting for logs...'}
        <div ref={bottomRef} />
      </pre>
    </div>
  )
}
```

- [ ] **Step 8: Create `ui/src/pages/Jobs.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { headers } from '../App.jsx'

export default function Jobs() {
  const [jobs, setJobs] = useState([])
  const [form, setForm] = useState({ job_id: '', schedule: '', message: '' })
  const [error, setError] = useState('')

  const reload = () => fetch('/api/jobs', { headers: headers() }).then(r => r.json()).then(setJobs)
  useEffect(() => { reload() }, [])

  const create = async () => {
    setError('')
    const r = await fetch('/api/jobs', { method: 'POST', headers: headers(), body: JSON.stringify(form) })
    if (!r.ok) { setError((await r.json()).detail); return }
    setForm({ job_id: '', schedule: '', message: '' })
    reload()
  }

  const remove = async (id) => {
    await fetch(`/api/jobs/${id}`, { method: 'DELETE', headers: headers() })
    reload()
  }

  return (
    <div>
      <h2>Jobs</h2>
      <table border="1" cellPadding="4">
        <thead><tr><th>ID</th><th>Next Run</th><th></th></tr></thead>
        <tbody>{jobs.map(j => (
          <tr key={j.id}>
            <td>{j.id}</td><td>{j.next_run}</td>
            <td><button onClick={() => remove(j.id)}>Delete</button></td>
          </tr>
        ))}</tbody>
      </table>
      <h3>New Job</h3>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {['job_id', 'schedule', 'message'].map(k => (
        <div key={k}>
          <label>{k}: </label>
          <input value={form[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} />
        </div>
      ))}
      <button onClick={create}>Create</button>
    </div>
  )
}
```

- [ ] **Step 9: Create `ui/src/pages/Agents.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { headers } from '../App.jsx'

export default function Agents() {
  const [data, setData] = useState({ planner: null, executors: {} })
  useEffect(() => {
    fetch('/api/agents', { headers: headers() }).then(r => r.json()).then(setData)
  }, [])

  return (
    <div>
      <h2>Agents</h2>
      {data.planner && (
        <div>
          <h3>Planner</h3>
          <p>Model: {data.planner.model}</p>
          <p>{data.planner.description}</p>
        </div>
      )}
      <h3>Executors</h3>
      {Object.entries(data.executors).map(([name, e]) => (
        <div key={name} style={{ marginBottom: '1rem', borderBottom: '1px solid #ccc' }}>
          <h4>{name}</h4>
          <p>Model: {e.model}</p>
          <p>{e.description}</p>
          <p>Tools: {e.tools.join(', ') || '(none)'}</p>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 10: Create `ui/src/pages/Memory.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { headers } from '../App.jsx'

export default function Memory() {
  const [data, setData] = useState({})
  const [path, setPath] = useState('')
  const [value, setValue] = useState('')
  const [msg, setMsg] = useState('')

  const reload = () => fetch('/api/memory', { headers: headers() }).then(r => r.json()).then(setData)
  useEffect(() => { reload() }, [])

  const update = async () => {
    let parsed
    try { parsed = JSON.parse(value) } catch { parsed = value }
    const r = await fetch('/api/memory', {
      method: 'PUT', headers: headers(),
      body: JSON.stringify({ path, value: parsed }),
    })
    setMsg(r.ok ? 'Updated.' : (await r.json()).detail)
    if (r.ok) reload()
  }

  return (
    <div>
      <h2>Core Memory</h2>
      <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem' }}>
        {JSON.stringify(data, null, 2)}
      </pre>
      <h3>Update</h3>
      <div><label>Path: </label><input value={path} onChange={e => setPath(e.target.value)} placeholder="user.name" /></div>
      <div><label>Value (JSON): </label><input value={value} onChange={e => setValue(e.target.value)} placeholder='"Alice"' /></div>
      <button onClick={update}>Update</button>
      {msg && <p>{msg}</p>}
    </div>
  )
}
```

- [ ] **Step 11: Create `ui/src/pages/Settings.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { headers } from '../App.jsx'

export default function Settings() {
  const [agents, setAgents] = useState(null)
  useEffect(() => {
    fetch('/api/agents', { headers: headers() }).then(r => r.json()).then(setAgents)
  }, [])

  return (
    <div>
      <h2>Settings</h2>
      <p style={{ color: '#888' }}>Read-only view of the current agent configuration.</p>
      {agents && (
        <pre style={{ background: '#111', color: '#ccc', padding: '0.5rem' }}>
          {JSON.stringify(agents, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 12: Install Node deps and verify build**

```bash
cd /root/kore-ai/ui && npm install && npm run build
```

Expected: build succeeds, `src/kore/ui/static/` populated with `index.html`, `assets/`

- [ ] **Step 13: Run full Python test suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

Expected: all Python tests still pass

- [ ] **Step 14: Commit**

```bash
cd /root/kore-ai
git add ui/ src/kore/ui/static/
git commit -m "feat: React/Vite dashboard — Overview, Logs, Jobs, Agents, Memory, Settings"
```

---

## Test Coverage Summary

All tests live in `tests/test_gateway.py`. The test matrix:

| Area | Tests |
|------|-------|
| Log handler buffer + listener | 4 |
| Auth (no creds, valid, invalid, disabled) | 4 |
| Rate limiting (429 on limit exceeded) | 1 |
| GET/POST/DELETE `/api/jobs` | 3 |
| GET `/api/agents` | 1 |
| GET/PUT/DELETE `/api/memory` | 3 |
| GET `/api/logs` | 1 |
| POST `/api/message` (success + 503) | 2 |
| WebSocket connect, receive, disconnect cleanup | 3 |
| Telegram webhook (success + 503) | 2 |
| App state injection | 1 |
| **Total** | **25** |

---

## Implementation Notes

**Auth in React:** `App.jsx` hardcodes `admin:secret`. In production, prompt for credentials and store in `sessionStorage`. For v1 personal use, hardcoding is acceptable.

**uvicorn signal conflict:** `uvicorn_server.install_signal_handlers = lambda: None` disables uvicorn's own signal handler so Kore's `loop.add_signal_handler` takes precedence. `_shutdown_watcher` monitors the stop event and sets `server.should_exit = True` to trigger uvicorn's graceful shutdown.

**Static file serving order:** FastAPI mounts the React SPA at `/` last, after all other routers are registered, so API and WebSocket routes take priority over the static file handler.

**Rate limit reset:** The `_rate_buckets` dict in `auth.py` is module-level and resets on process restart. This is acceptable for a personal assistant — no Redis required in v1.
