from __future__ import annotations

import json
from pathlib import Path

from kore.config import KORE_HOME

# ---------------------------------------------------------------------------
# Templates written by `kore init`
# ---------------------------------------------------------------------------

_CONFIG_TEMPLATE = {
    "version": "1.0.0",
    "debug": {"session_tracing": True},
    "llm": {
        "providers": {
            "anthropic": {"api_key_env": "ANTHROPIC_API_KEY"},
            "openai":    {"api_key_env": "OPENAI_API_KEY"},
            "openrouter": {
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://openrouter.ai/api/v1",
            },
            "ollama": {"base_url": "http://localhost:11434/v1"},
        }
    },
    "agents": {
        "primary": {
            "model": "anthropic:claude-sonnet-4-6",
            "prompt": "prompts/primary.md",
            "tools": ["*"],
            "skills": ["*"],
            "shell_allowlist": [],
            "usage_limits": {
                "request_limit": 30,
                "total_tokens_limit": 200000,
                "tool_calls_limit": 25,
            },
        },
        "subagents": {
            "deep_research": {
                "model": "anthropic:claude-haiku-4-5-20251001",
                "prompt": "prompts/deep_research.md",
                "tools": ["web_search", "scrape_url", "memory_search"],
                "skills": ["search-topic-online"],
                "shell_allowlist": [],
                "usage_limits": {
                    "request_limit": 10,
                    "total_tokens_limit": 80000,
                    "tool_calls_limit": 12,
                },
            },
            "draft_longform": {
                "model": "anthropic:claude-sonnet-4-6",
                "prompt": "prompts/draft_longform.md",
                "tools": ["memory_search", "read_file"],
                "skills": ["content-writer"],
                "shell_allowlist": [],
                "usage_limits": {
                    "request_limit": 6,
                    "total_tokens_limit": 60000,
                    "tool_calls_limit": 8,
                },
            },
        },
    },
    "tools": {
        "web_search": {
            "provider": "brave",
            "api_key_env": "BRAVE_API_KEY",
            "max_results": 5,
        }
    },
    "channels": {
        "telegram": {
            "bot_token_env": "TELEGRAM_BOT_TOKEN",
            "allowed_user_ids": [],
        }
    },
    "scheduler": {
        "timezone": "UTC",
        "data_jobs_file": "data/jobs.json",
    },
    "memory": {
        "core": {"path": "data/core_memory.json", "max_tokens": 4000},
        "event_log": {"vector_weight": 0.7, "bm25_weight": 0.3, "top_k": 10},
        "consolidation": {"model": "anthropic:claude-haiku-4-5-20251001", "interval_minutes": 30},
    },
    "security": {"max_tool_calls_per_request": 8},
    "ui": {"port": 8000, "host": "0.0.0.0"},
}

_JOBS_TEMPLATE = {"jobs": []}

_SOUL_TEMPLATE = """\
<!-- Fill in this file to define Kore's personality. Leave sections empty to skip them. -->

## Identity
<!-- Who is Kore? One sentence describing the assistant's character. -->

## Communication Style
<!-- Tone, response length defaults, formatting preferences. -->
<!-- Example: Direct and concise. Default to 2-3 sentences. Use bullet points for lists. -->

## Values
<!-- What Kore prioritizes when trade-offs arise. -->
<!-- Example: Accuracy over speed. Honesty over politeness. -->

## Anti-patterns
<!-- Behaviors and phrases Kore avoids. -->
<!-- Example: Never start a response with "Certainly!" or "Great question!". -->
"""

_USER_TEMPLATE = """\
<!-- Fill in this file to tell Kore about you. Leave sections empty to skip them. -->

## Basic Info
<!-- Name, location, timezone, what you do. -->

## Preferences
<!-- How you like to receive information. Response style, verbosity, format. -->

## Current Projects
<!-- What you are working on right now. Brief description per project. -->

## Priorities
<!-- What matters most to you right now. -->
"""

_ENV_EXAMPLE = """\
# Required
ANTHROPIC_API_KEY=your-anthropic-api-key
BRAVE_API_KEY=your-brave-search-api-key
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Optional — set to enable webhook mode (production); omit to use polling (local dev)
# TELEGRAM_WEBHOOK_URL=https://your-domain.com/webhook

# Optional — only needed if using alternative LLM providers
OPENAI_API_KEY=your-openai-or-openrouter-api-key
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_if_absent(path: Path, content: str) -> None:
    """Write content to path if it does not exist; otherwise warn and skip."""
    if path.exists():
        print(f"  [skipping] {path} already exists")
        return
    path.write_text(content)
    print(f"  [created]  {path}")


def _mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init() -> None:
    """Create ~/.kore directory structure with template files."""
    home = KORE_HOME
    print(f"Initialising Kore home at {home}")

    _mkdir(home)
    _mkdir(home / "data")
    _mkdir(home / "workspace" / "skills")
    _mkdir(home / "workspace" / "files")

    _write_if_absent(home / "config.json", json.dumps(_CONFIG_TEMPLATE, indent=2))
    _write_if_absent(home / "data" / "jobs.json", json.dumps(_JOBS_TEMPLATE, indent=2))
    _write_if_absent(home / ".env.example", _ENV_EXAMPLE)
    _write_if_absent(home / "SOUL.md", _SOUL_TEMPLATE)
    _write_if_absent(home / "USER.md", _USER_TEMPLATE)

    print("\nDone. Next steps:")
    print(f"  1. Edit {home / 'config.json'} — set your model preferences")
    print(f"  2. Copy {home / '.env.example'} → {home / '.env'} and fill in API keys")
    print(f"  3. Edit {home / 'SOUL.md'} — define Kore's personality (optional)")
    print(f"  4. Edit {home / 'USER.md'} — tell Kore about yourself (optional)")
    print("  5. Run: kore gateway")


def cmd_migrate() -> None:
    """Apply any pending migrations to ~/.kore. (Stub — nothing to migrate in Phase 1.)"""
    print("Nothing to migrate.")
