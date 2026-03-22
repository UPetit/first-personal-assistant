from __future__ import annotations

import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_update(text: str, user_id: int = 111, chat_id: int = 111, is_command: bool = False):
    """Build a minimal mock telegram.Update."""
    from telegram import Chat, Update, User

    user = User(id=user_id, first_name="Test", is_bot=False, username="testuser")
    chat = MagicMock()
    chat.id = chat_id

    message = MagicMock()
    message.text = text
    message.chat = chat
    message.from_user = user
    message.reply_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.message = message
    update.effective_user = user
    update.effective_chat = chat
    return update


# ── _md_to_telegram_html ─────────────────────────────────────────────────────

def test_md_plain_text_is_unchanged():
    from kore.channels.telegram import _md_to_telegram_html
    assert _md_to_telegram_html("hello world") == "hello world"


def test_md_html_special_chars_escaped():
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("a < b & c > d")
    assert result == "a &lt; b &amp; c &gt; d"


def test_md_no_numeric_entities():
    """Telegram only recognises &lt; &gt; &amp; &quot; — no &#x27; etc."""
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("it's a test \"quoted\"")
    assert "&#" not in result
    assert "it's" in result


def test_md_bold():
    from kore.channels.telegram import _md_to_telegram_html
    assert _md_to_telegram_html("**bold**") == "<b>bold</b>"


def test_md_italic_asterisk():
    from kore.channels.telegram import _md_to_telegram_html
    assert _md_to_telegram_html("*italic*") == "<i>italic</i>"


def test_md_heading_becomes_bold():
    from kore.channels.telegram import _md_to_telegram_html
    assert _md_to_telegram_html("## Solana") == "<b>Solana</b>"


def test_md_horizontal_rule_becomes_blank():
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("before\n---\nafter")
    assert "---" not in result
    assert "before" in result and "after" in result


def test_md_blockquote():
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("> a warning")
    assert "<blockquote>" in result
    assert "a warning" in result


def test_md_inline_code():
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("call `foo()` now")
    assert "<code>foo()</code>" in result


def test_md_fenced_code_block():
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("```python\nprint('hi')\n```")
    assert "<pre>" in result and "print('hi')" in result


def test_md_table_rendered_as_pre():
    from kore.channels.telegram import _md_to_telegram_html
    table = "| Metric | Value |\n|---|---|\n| Price | $100 |"
    result = _md_to_telegram_html(table)
    # Rendered inside a <pre> block with aligned columns
    assert "<pre>" in result
    assert "Metric" in result
    assert "Price" in result
    assert "$100" in result
    # Markdown separator row must be gone
    assert "---|---" not in result


def test_md_table_columns_aligned():
    from kore.channels.telegram import _md_to_telegram_html
    table = "| A | BB |\n|---|---|\n| CCC | D |"
    result = _md_to_telegram_html(table)
    # Both "A" and "CCC" are left-justified in same-width column,
    # so header row has a "─" separator.
    assert "─" in result


def test_md_link():
    from kore.channels.telegram import _md_to_telegram_html
    result = _md_to_telegram_html("[Click here](https://example.com)")
    assert '<a href="https://example.com">Click here</a>' in result


def test_md_full_price_example():
    """End-to-end: the SOL price message renders without raw markdown syntax."""
    from kore.channels.telegram import _md_to_telegram_html
    msg = (
        "## 🟣 Solana (SOL)\n\n"
        "| Metric | Value |\n"
        "|---|---|\n"
        "| 💰 **Price** | ~**$89.89** |\n\n"
        "---\n\n"
        "> ⚠️ *Prices are volatile.*\n"
    )
    result = _md_to_telegram_html(msg)
    assert "##" not in result
    assert "---|---" not in result
    assert "<b>🟣 Solana (SOL)</b>" in result
    assert "<pre>" in result
    assert "$89.89" in result
    assert "<blockquote>" in result


# ── chunk_text ────────────────────────────────────────────────────────────────

def test_chunk_text_short():
    from kore.channels.telegram import _chunk_text
    assert _chunk_text("hello") == ["hello"]


def test_chunk_text_exact_limit():
    from kore.channels.telegram import _chunk_text
    text = "a" * 4096
    chunks = _chunk_text(text)
    assert chunks == [text]


def test_chunk_text_splits_long():
    from kore.channels.telegram import _chunk_text
    text = "x" * 9000
    chunks = _chunk_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks) == text


# ── _is_allowed ───────────────────────────────────────────────────────────────

def _make_channel(allowed_user_ids: list[int]):
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from pydantic import SecretStr

    cfg = TelegramConfig(
        bot_token=SecretStr("fake:TOKEN"),
        allowed_user_ids=allowed_user_ids,
    )
    # Patch Application for the duration of __init__, then replace _app with a
    # persistent mock so tests that call methods on the channel work outside the
    # patch context.
    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
    # _app is already mock_app (set by __init__ via the patched builder),
    # but we reassign explicitly for clarity and forward-compatibility.
    channel._app = mock_app
    return channel


def test_is_allowed_empty_list_allows_all():
    channel = _make_channel([])
    assert channel._is_allowed(99999) is True


def test_is_allowed_whitelist_blocks_unknown():
    channel = _make_channel([111, 222])
    assert channel._is_allowed(999) is False


def test_is_allowed_whitelist_permits_known():
    channel = _make_channel([111, 222])
    assert channel._is_allowed(111) is True


# ── message normalisation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_message_pushes_to_queue():
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from kore.gateway.queue import MessageQueue
    from pydantic import SecretStr

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    queue = MessageQueue()

    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app.bot.send_message = AsyncMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
        channel._app = mock_app
        channel._queue = queue

        update = _make_update("Hello Kore", user_id=111)
        ctx = MagicMock()
        await channel._on_message(update, ctx)

    assert queue.qsize() == 1
    msg = await queue.get()
    assert msg.text == "Hello Kore"
    assert msg.channel == "telegram"
    assert msg.session_id == "telegram_111"
    assert msg.user_id == "111"


@pytest.mark.asyncio
async def test_on_message_blocks_unknown_user():
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from kore.gateway.queue import MessageQueue
    from pydantic import SecretStr

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    queue = MessageQueue()

    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
        channel._app = mock_app
        channel._queue = queue

        update = _make_update("Hello", user_id=999)
        await channel._on_message(update, MagicMock())

    assert queue.qsize() == 0


# ── commands ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_command_replies():
    channel = _make_channel([111])
    update = _make_update("/status", user_id=111)
    await channel._cmd_status(update, MagicMock())
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "running" in reply_text.lower()


@pytest.mark.asyncio
async def test_status_command_blocks_unknown():
    channel = _make_channel([111])
    update = _make_update("/status", user_id=999)
    await channel._cmd_status(update, MagicMock())
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_command_replies_no_active_task():
    channel = _make_channel([111])
    update = _make_update("/cancel", user_id=111)
    await channel._cmd_cancel(update, MagicMock())
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "cancel" in reply_text.lower()


@pytest.mark.asyncio
async def test_jobs_command_no_callback():
    channel = _make_channel([111])  # no get_jobs_text callback
    update = _make_update("/jobs", user_id=111)
    await channel._cmd_jobs(update, MagicMock())
    update.message.reply_text.assert_called_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "scheduler" in reply_text.lower() or "no" in reply_text.lower()


@pytest.mark.asyncio
async def test_jobs_command_with_callback():
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from pydantic import SecretStr

    async def fake_jobs() -> str:
        return "- daily_digest: next_run=2026-03-18 08:00"

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg, get_jobs_text=fake_jobs)
        channel._app = mock_app

    update = _make_update("/jobs", user_id=111)
    await channel._cmd_jobs(update, MagicMock())
    reply_text = update.message.reply_text.call_args[0][0]
    assert "daily_digest" in reply_text


@pytest.mark.asyncio
async def test_memory_command_no_callback():
    channel = _make_channel([111])  # no get_memory_text callback
    update = _make_update("/memory", user_id=111)
    await channel._cmd_memory(update, MagicMock())
    update.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_memory_command_with_callback():
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from pydantic import SecretStr

    async def fake_memory() -> str:
        return "```json\n{\"user\": {\"name\": \"Alice\"}}\n```"

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg, get_memory_text=fake_memory)
        channel._app = mock_app

    update = _make_update("/memory", user_id=111)
    await channel._cmd_memory(update, MagicMock())
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Alice" in reply_text


@pytest.mark.asyncio
async def test_send_chunks_long_message():
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from pydantic import SecretStr

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"))
    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        mock_app = MagicMock()
        mock_app.bot = mock_bot
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
        channel._app = mock_app

        long_text = "w" * 10000
        await channel.send("111", long_text)

    assert mock_bot.send_message.call_count == 3


# ── rejection logging ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_new_sets_new_session_id(kore_home):
    """/new command assigns a fresh timestamped session_id for subsequent messages."""
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from kore.gateway.queue import MessageQueue
    from pydantic import SecretStr

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    queue = MessageQueue()

    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
        channel._app = mock_app
        channel._queue = queue

    # Before /new: resolves to default (no session files exist yet)
    update = _make_update("Hello", user_id=111)
    await channel._on_message(update, MagicMock())
    msg = await queue.get()
    assert msg.session_id == "telegram_111"

    # Issue /new
    new_update = _make_update("/new", user_id=111)
    await channel._cmd_new(new_update, MagicMock())
    new_update.message.reply_text.assert_called_once()
    assert "New session" in new_update.message.reply_text.call_args[0][0]

    # After /new: new timestamped session id
    update2 = _make_update("First message in new session", user_id=111)
    await channel._on_message(update2, MagicMock())
    msg2 = await queue.get()
    assert msg2.session_id.startswith("telegram_111_")
    assert msg2.session_id != "telegram_111"


@pytest.mark.asyncio
async def test_resolve_session_resumes_latest_on_restart(kore_home):
    """After a restart (_active_sessions cleared), the most recently modified
    session file is resumed rather than falling back to the default."""
    import json, time
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from kore.gateway.queue import MessageQueue
    from kore.session.buffer import _sessions_dir
    from pydantic import SecretStr

    # Write two session files with different mtimes
    sess_dir = _sessions_dir()
    sess_dir.mkdir(parents=True, exist_ok=True)
    old_file = sess_dir / "telegram_111.json"
    new_file = sess_dir / "telegram_111_20260322_120000.json"
    old_file.write_text(json.dumps({"session_id": "telegram_111", "created_at": "2026-03-20T10:00:00+00:00", "summary": None, "turns": []}))
    time.sleep(0.01)
    new_file.write_text(json.dumps({"session_id": "telegram_111_20260322_120000", "created_at": "2026-03-22T12:00:00+00:00", "summary": None, "turns": []}))

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    queue = MessageQueue()
    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
        channel._app = mock_app
        channel._queue = queue

    update = _make_update("Hi again", user_id=111)
    await channel._on_message(update, MagicMock())
    msg = await queue.get()
    assert msg.session_id == "telegram_111_20260322_120000"


@pytest.mark.asyncio
async def test_cmd_new_blocks_unknown_user():
    """/new from an unauthorised user_id must be silently dropped."""
    from kore.channels.telegram import TelegramChannel
    from kore.config import TelegramConfig
    from pydantic import SecretStr

    cfg = TelegramConfig(bot_token=SecretStr("fake:TOKEN"), allowed_user_ids=[111])
    with patch("kore.channels.telegram.Application") as mock_app_cls:
        mock_app = MagicMock()
        mock_app_cls.builder.return_value.token.return_value.build.return_value = mock_app
        channel = TelegramChannel(cfg)
        channel._app = mock_app

    update = _make_update("/new", user_id=999)
    await channel._cmd_new(update, MagicMock())
    update.message.reply_text.assert_not_called()


def test_is_allowed_logs_rejection_at_debug(caplog):
    """Rejecting an unknown user_id must emit a DEBUG log."""
    channel = _make_channel([111, 222])
    with caplog.at_level(logging.DEBUG, logger="kore.channels.telegram"):
        result = channel._is_allowed(999)
    assert result is False
    assert any("999" in record.message for record in caplog.records)
    assert any(record.levelno == logging.DEBUG for record in caplog.records)
