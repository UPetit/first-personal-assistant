from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from pathlib import Path

from kore.config import load_config, KORE_HOME
from kore.gateway.queue import MessageQueue
from kore.channels.telegram import TelegramChannel
from kore.scheduler.cron import KoreCronScheduler
from kore.tools import cron_tools
from kore.agents.orchestrator import Orchestrator
from kore.channels.base import Channel, Message

logger = logging.getLogger(__name__)


async def _consume(queue: MessageQueue, orchestrator: _OrchestratorAdapter) -> None:
    """Pull messages off the queue and run the orchestrator pipeline."""
    try:
        while True:
            msg = await queue.get()
            try:
                await orchestrator.run(msg)
            except Exception as exc:
                logger.exception("Orchestrator error for message %r: %s", msg.text, exc)
            finally:
                queue.task_done()
    except asyncio.CancelledError:
        logger.info("Consumer loop cancelled, shutting down.")


class _OrchestratorAdapter:
    """Adapts the Orchestrator.run(text, session_id) signature to run(Message)."""

    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator

    async def run(self, msg: Message) -> None:
        response = await self._orchestrator.run(msg.text, msg.session_id)
        try:
            await msg.reply(response.content)
        except Exception as exc:
            logger.warning("Reply failed for session %r: %s", msg.session_id, exc)


async def main() -> None:
    config = load_config()
    from kore.gateway.trace_store import TraceStore
    trace_store: TraceStore | None = None
    if config.debug.session_tracing:
        trace_store = TraceStore(KORE_HOME / "kore.db")
        await trace_store.cleanup_old(days=7)
    queue = MessageQueue(maxsize=config.security.queue_maxsize)

    # Build scheduler
    jobs_file = KORE_HOME / config.scheduler.data_jobs_file
    scheduler = KoreCronScheduler(
        jobs_file=jobs_file,
        queue=queue,
        timezone=config.scheduler.timezone,
    )
    cron_tools.init(scheduler)
    scheduler.start()

    # Build orchestrator
    raw_orchestrator = Orchestrator(config, trace_store=trace_store)
    orchestrator = _OrchestratorAdapter(raw_orchestrator)

    # TODO: wire consolidation timer

    # Build and start channel(s) — after orchestrator is ready so no messages
    # are dispatched before all dependencies are initialised.
    channels: list[Channel] = []
    telegram_channel: TelegramChannel | None = None
    if config.channels.telegram is not None:
        telegram_channel = TelegramChannel(config.channels.telegram)
        channels.append(telegram_channel)
        # Wire cron sender so scheduled job results reach the Telegram user.
        tg_cfg = config.channels.telegram
        if tg_cfg.allowed_user_ids:
            scheduler.init_sender(
                telegram_channel.send,
                str(tg_cfg.allowed_user_ids[0]),
            )
        await telegram_channel.start(queue)
        webhook_url = config.channels.telegram.webhook_url
        if webhook_url:
            await telegram_channel.set_webhook(webhook_url)
        else:
            logger.warning(
                "No webhook_url configured for Telegram — falling back to polling. "
                "Set 'webhook_url_env: TELEGRAM_WEBHOOK_URL' in channels.telegram to enable webhook mode."
            )
            await telegram_channel.start_polling()

    # Build FastAPI app (raw_orchestrator accessible for /api/message)
    from kore.gateway.server import create_app
    app = create_app(
        config,
        queue=queue,
        scheduler=scheduler,
        orchestrator=raw_orchestrator,
        telegram_channel=telegram_channel,
        trace_store=trace_store,
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
    uvicorn_cfg = uvicorn.Config(
        app,
        host=config.ui.host,
        port=config.ui.port,
        log_config=None,  # use Kore's logging config
    )
    uvicorn_server = uvicorn.Server(uvicorn_cfg)
    uvicorn_server.install_signal_handlers = lambda: None  # we handle signals ourselves

    logger.info("Kore is running on http://%s:%d", config.ui.host, config.ui.port)

    # Run uvicorn and the shutdown watcher concurrently; the consumer task is
    # managed separately so we can cancel it cleanly after uvicorn exits.
    consume_task = asyncio.create_task(_consume(queue, orchestrator))

    await asyncio.gather(
        uvicorn_server.serve(),
        _shutdown_watcher(),
        return_exceptions=True,
    )

    # uvicorn has exited — cancel the consumer and wait for it to finish.
    consume_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await consume_task

    # Graceful teardown
    scheduler.stop()
    for ch in channels:
        await ch.stop()
    logger.info("Kore stopped.")


def _cli_main() -> None:
    """CLI entry point. Dispatches to init / migrate / gateway sub-commands."""
    command = sys.argv[1] if len(sys.argv) > 1 else "gateway"

    if command == "init":
        from kore.init import cmd_init
        cmd_init()
    elif command == "migrate":
        from kore.init import cmd_migrate
        cmd_migrate()
    elif command == "gateway":
        from kore.logging_config import configure_logging
        configure_logging(level=logging.INFO, json_format=False)
        asyncio.run(main())
    else:
        print(f"Unknown command: {command!r}. Available: init, migrate, gateway")
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()
