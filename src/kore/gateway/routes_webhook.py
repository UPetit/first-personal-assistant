from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram webhook POST and hand it to the TelegramChannel adapter.

    Note: this endpoint is NOT protected by require_auth — Telegram's servers
    POST to it directly. Security is provided by verifying the webhook secret
    (configured in TelegramConfig) in a future hardening pass.
    """
    channel = request.app.state.telegram_channel
    if channel is None:
        return Response(content="Telegram channel not configured", status_code=503)
    data = await request.json()
    await channel.process_update(data)
    return Response(status_code=200)
