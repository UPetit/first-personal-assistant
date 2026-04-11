from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
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
    from kore.gateway.trace_store import TraceStore
    from kore.memory.core_memory import CoreMemory
    from kore.scheduler.cron import KoreCronScheduler
    from kore.skills.registry import SkillRegistry

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
    trace_store: TraceStore | None = None,
    skill_registry: SkillRegistry | None = None,
) -> FastAPI:
    """Build and return the FastAPI application.

    All Kore components are injected via parameters and stored in ``app.state``
    so routes can access them without global imports.
    """
    log_handler = WebSocketLogHandler()
    log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
    app.state.trace_store = trace_store
    app.state.skill_registry = skill_registry

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
