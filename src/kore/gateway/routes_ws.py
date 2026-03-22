from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)

_REPLAY_COUNT = 100  # entries replayed to late-joining clients


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket) -> None:
    """Stream log entries to connected clients in real time.

    Each connection gets its own asyncio.Queue registered in WebSocketLogHandler.
    On connect, recent log history is replayed so late-joining clients get context.
    Disconnecting (or any send failure) cleans up the listener automatically.

    Note: client-side disconnect is detected only when a send or receive fails.
    On a quiet system a silently-closed client will linger until the next broadcast.
    """
    await websocket.accept()
    log_handler = websocket.app.state.log_handler
    queue = log_handler.add_listener()
    # Replay recent history for late-joining clients
    for entry in log_handler.recent(_REPLAY_COUNT):
        await websocket.send_text(entry)
    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("WebSocket /ws/logs closed with unexpected error", exc_info=True)
    finally:
        log_handler.remove_listener(queue)
