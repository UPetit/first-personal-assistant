from __future__ import annotations

import html as _html
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import asyncio

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from kore.channels.base import Channel, Message, noop_reply
from kore.config import TelegramConfig
from kore.gateway.queue import MessageQueue

logger = logging.getLogger(__name__)


def _chunk_text(text: str, max_len: int = 4096) -> list[str]:
    """Split *text* into chunks of at most *max_len* characters."""
    if len(text) <= max_len:
        return [text]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


def _esc(text: str) -> str:
    """Escape only the three characters Telegram requires: ``&``, ``<``, ``>``."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _strip_md_inline(text: str) -> str:
    """Remove Markdown inline markers, returning plain text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*([^\*\n]+?)\*", r"\1", text)
    text = re.sub(r"_([^_\n]+?)_", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"`([^`\n]+?)`", r"\1", text)
    return text


def _md_to_telegram_html(text: str) -> str:
    """Convert common Markdown to Telegram-compatible HTML.

    Telegram only supports: ``<b>``, ``<i>``, ``<u>``, ``<s>``, ``<code>``,
    ``<pre>``, ``<a>``, ``<blockquote>``.  No ``<table>``, ``<p>``, ``<h>``,
    ``<ul>``/``<ol>``, ``<br>``, ``<hr>``, or numeric HTML entities.

    Tables are rendered inside ``<pre>`` with column-aligned plain text.
    """
    stash: dict[str, str] = {}
    n = 0

    def _save(repl: str) -> str:
        nonlocal n
        key = f"\x00{n}\x00"
        stash[key] = repl
        n += 1
        return key

    # ── stash fenced code blocks ─────────────────────────────────────────
    text = re.sub(
        r"```(?:\w*\n?)(.*?)```",
        lambda m: _save(f"<pre>{_esc(m.group(1).strip())}</pre>"),
        text,
        flags=re.DOTALL,
    )
    # ── stash inline code ────────────────────────────────────────────────
    text = re.sub(
        r"`([^`\n]+)`",
        lambda m: _save(f"<code>{_esc(m.group(1))}</code>"),
        text,
    )

    # ── inline formatting (for already-escaped text) ─────────────────────
    def _inline(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\*([^\*\n]+?)\*", r"<i>\1</i>", s)
        s = re.sub(r"_([^_\n]+?)_", r"<i>\1</i>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    # ── tables → <pre> with aligned columns ──────────────────────────────
    def _table_to_pre(block: str) -> str:
        rows: list[list[str]] = []
        for ln in block.strip().splitlines():
            if re.match(r"^\|[\s\-:|]+\|$", ln.strip()):
                continue  # separator row
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows.append([_strip_md_inline(c) for c in cells if c])
        if not rows:
            return ""
        # Calculate column widths.
        col_count = max(len(r) for r in rows)
        widths = [0] * col_count
        for row in rows:
            for ci, cell in enumerate(row):
                widths[ci] = max(widths[ci], len(cell))
        # Build aligned text lines.
        lines: list[str] = []
        for i, row in enumerate(rows):
            parts = []
            for ci in range(col_count):
                cell = row[ci] if ci < len(row) else ""
                parts.append(cell.ljust(widths[ci]))
            lines.append("  ".join(parts).rstrip())
            # Add a separator after the header row.
            if i == 0:
                lines.append("  ".join("─" * w for w in widths))
        return "<pre>" + _esc("\n".join(lines)) + "</pre>"

    def _replace_tables(src: str) -> str:
        lines = src.splitlines(keepends=True)
        result: list[str] = []
        i = 0
        while i < len(lines):
            if lines[i].lstrip().startswith("|"):
                j = i
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    j += 1
                result.append(_save(_table_to_pre("".join(lines[i:j]))) + "\n")
                i = j
            else:
                result.append(lines[i])
                i += 1
        return "".join(result)

    text = _replace_tables(text)

    # ── process block-level elements line by line ────────────────────────
    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()

        # Horizontal rule → blank line
        if re.match(r"^[-*_]{3,}$", stripped.strip()):
            out_lines.append("")
            continue

        # ATX heading → bold line
        m = re.match(r"^#{1,6}\s+(.+)$", stripped)
        if m:
            out_lines.append("<b>" + _inline(_esc(m.group(1))) + "</b>")
            continue

        # Blockquote → <blockquote>
        m = re.match(r"^>\s*(.*)", stripped)
        if m:
            out_lines.append(
                "<blockquote>" + _inline(_esc(m.group(1))) + "</blockquote>"
            )
            continue

        # Regular line – escape then apply inline formatting.
        out_lines.append(_inline(_esc(stripped)))

    result = "\n".join(out_lines)

    # Restore stashed blocks.
    for key, val in stash.items():
        result = result.replace(key, val)

    # Collapse runs of 3+ blank lines to 2.
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


class TelegramChannel(Channel):
    """Telegram channel adapter using python-telegram-bot v20+ Application.

    In Phase 5, call ``start()`` + ``app.updater.start_polling()`` for dev/testing.
    In Phase 6, the FastAPI route calls ``process_update(data)`` for webhook mode.
    """

    def __init__(
        self,
        config: TelegramConfig,
        get_jobs_text: Callable[[], Awaitable[str]] | None = None,
        get_memory_text: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._config = config
        self._queue: MessageQueue | None = None
        self._get_jobs_text = get_jobs_text
        self._get_memory_text = get_memory_text
        self._active_sessions: dict[str, str] = {}  # uid → current session_id
        self._typing_tasks: dict[str, asyncio.Task] = {}  # uid → typing loop task

        if not config.bot_token:
            raise ValueError(
                "TelegramChannel requires a bot_token. "
                "Set 'bot_token_env' in config.json to reference the env var."
            )
        token = config.bot_token.get_secret_value()
        self._app: Application = Application.builder().token(token).build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("jobs", self._cmd_jobs))
        self._app.add_handler(CommandHandler("memory", self._cmd_memory))
        self._app.add_handler(CommandHandler("cancel", self._cmd_cancel))
        self._app.add_handler(CommandHandler("new", self._cmd_new))

    # ── Channel ABC ───────────────────────────────────────────────────────────

    async def _typing_loop(self, chat_id: int) -> None:
        """Send a typing action every 4 s until cancelled."""
        try:
            while True:
                await self._app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    def _start_typing(self, uid: str, chat_id: int) -> None:
        """Cancel any existing typing task for *uid* and start a fresh one."""
        existing = self._typing_tasks.pop(uid, None)
        if existing:
            existing.cancel()
        self._typing_tasks[uid] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, uid: str) -> None:
        """Cancel and remove the typing task for *uid* if one exists."""
        task = self._typing_tasks.pop(uid, None)
        if task:
            task.cancel()

    async def send(self, user_id: str, text: str) -> None:
        """Send *text* to *user_id*, splitting into ≤4096-char chunks.

        Converts Markdown to Telegram HTML.  Falls back to plain text if
        Telegram rejects the HTML (e.g. due to an edge-case formatting issue).
        Cancels the typing indicator before sending.
        """
        self._stop_typing(user_id)
        formatted = _md_to_telegram_html(text)
        for chunk in _chunk_text(formatted):
            try:
                await self._app.bot.send_message(
                    chat_id=int(user_id), text=chunk, parse_mode="HTML"
                )
            except Exception:
                logger.debug("HTML send failed, falling back to plain text")
                plain = _chunk_text(text)
                for pc in plain:
                    await self._app.bot.send_message(
                        chat_id=int(user_id), text=pc
                    )
                return

    async def start(self, queue: MessageQueue) -> None:
        """Initialise the Application and register the message queue."""
        self._queue = queue
        await self._app.initialize()
        await self._app.start()

    async def set_webhook(self, webhook_url: str) -> None:
        """Register the webhook URL with Telegram (called once at startup)."""
        full_url = f"{webhook_url.rstrip('/')}/telegram/webhook"
        await self._app.bot.set_webhook(url=full_url)
        logger.info("Telegram webhook registered: %s", full_url)

    async def start_polling(self) -> None:
        """Start long-polling (for local dev without a public webhook URL).

        Deletes any previously registered webhook first — an active webhook
        causes getUpdates to return 409 Conflict, silently killing polling.
        drop_pending_updates=True prevents replaying stale queued messages.
        """
        if self._app.updater is None:
            raise RuntimeError("Application was built without an updater — polling not available")
        await self._app.bot.delete_webhook(drop_pending_updates=True)
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram polling started")

    async def stop(self) -> None:
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    # ── Webhook integration (Phase 6) ─────────────────────────────────────────

    async def process_update(self, data: dict) -> None:
        """Decode a raw webhook POST body and hand it to the Application.

        Called by the FastAPI webhook route in Phase 6.
        """
        update = Update.de_json(data, self._app.bot)
        await self._app.process_update(update)

    # ── internals ─────────────────────────────────────────────────────────────

    def _resolve_session(self, uid: str) -> str:
        """Return the active session ID for *uid*.

        On first call after a restart the in-memory cache is empty, so we scan
        the sessions directory for the most recently modified file belonging to
        this user and resume it. Falls back to the default ``telegram_{uid}``
        session (which SessionBuffer will create fresh if it doesn't exist yet).
        """
        if uid in self._active_sessions:
            return self._active_sessions[uid]

        from kore.session.buffer import _sessions_dir
        sess_dir = _sessions_dir()
        if sess_dir.exists():
            candidates = list(sess_dir.glob(f"telegram_{uid}*.json"))
            if candidates:
                latest = max(candidates, key=lambda p: p.stat().st_mtime)
                session_id = latest.stem
                self._active_sessions[uid] = session_id
                return session_id

        self._active_sessions[uid] = f"telegram_{uid}"
        return self._active_sessions[uid]

    def _is_allowed(self, user_id: int) -> bool:
        if not self._config.allowed_user_ids:
            return True
        allowed = user_id in self._config.allowed_user_ids
        if not allowed:
            logger.debug("Rejected message from unauthorized user_id=%s", user_id)
        return allowed

    async def _on_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        uid = str(update.effective_user.id)
        self._start_typing(uid, update.effective_user.id)
        session_id = self._resolve_session(uid)
        msg = Message(
            text=update.message.text,
            channel="telegram",
            session_id=session_id,
            user_id=uid,
            reply=lambda text, _uid=uid: self.send(_uid, text),
        )
        if self._queue is None:
            raise RuntimeError("start() must be called before messages arrive")
        await self._queue.put(msg)

    async def _cmd_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        await update.message.reply_text("Kore is running.")

    async def _cmd_jobs(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        if self._get_jobs_text is not None:
            text = await self._get_jobs_text()
        else:
            text = "(no scheduler connected)"
        await update.message.reply_text(text or "(no scheduled jobs)")

    async def _cmd_memory(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        if self._get_memory_text is not None:
            text = await self._get_memory_text()
        else:
            text = "(no memory connected)"
        await update.message.reply_text(text)

    async def _cmd_cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        await update.message.reply_text("No active task to cancel.")

    async def _cmd_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not self._is_allowed(update.effective_user.id):
            return
        uid = str(update.effective_user.id)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._active_sessions[uid] = f"telegram_{uid}_{ts}"
        await update.message.reply_text("New session started. Previous conversation history cleared.")
