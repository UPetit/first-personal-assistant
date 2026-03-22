from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kore.gateway.queue import MessageQueue


@dataclass
class Message:
    """Normalised inbound message from any channel.

    ``reply`` is a bound async callable that sends a response back to the
    originating channel/user. For CRON-fired messages it is a no-op.
    """

    text: str
    channel: str            # "telegram" | "api" | "cron"
    session_id: str         # session key (used by SessionBuffer)
    user_id: str            # Telegram user id, "cron", or "api"
    reply: Callable[[str], Awaitable[None]] = field(repr=False)


async def noop_reply(text: str) -> None:  # noqa: ARG001
    """No-op reply for messages that don't need a response (e.g. CRON-fired)."""


class Channel(ABC):
    """Abstract base for all inbound/outbound channel adapters."""

    @abstractmethod
    async def send(self, user_id: str, text: str) -> None:
        """Send *text* to *user_id* in this channel."""

    @abstractmethod
    async def start(self, queue: MessageQueue) -> None:
        """Start receiving messages and pushing them to *queue*."""

    @abstractmethod
    async def stop(self) -> None:
        """Shut down the channel cleanly."""
