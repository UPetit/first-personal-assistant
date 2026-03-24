from __future__ import annotations

import json
from pathlib import Path

from kore.config import KORE_HOME

# ---------------------------------------------------------------------------
# Templates written by `kore init`
# ---------------------------------------------------------------------------

_CONFIG_TEMPLATE = {
    "version": "1.0.0",
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
        "planner": {
            "model": "anthropic:claude-sonnet-4-6",
            "prompt_file": "planner.md",
            "tools": [],
        },
        "executors": {
            "general": {
                "model": "anthropic:claude-sonnet-4-6",
                "prompt_file": "general.md",
                "tools": ["web_search", "scrape_url", "get_current_time", "core_memory_update", "core_memory_delete", "memory_search", "memory_store"],
                "skills": ["*"],
                "description": "Handles complex or mixed tasks requiring multiple capabilities",
            },
            "search": {
                "model": "anthropic:claude-haiku-4-5-20251001",
                "prompt_file": "search.md",
                "tools": ["web_search", "scrape_url", "get_current_time"],
                "description": "Web research and information retrieval",
            },
            "writer": {
                "model": "anthropic:claude-haiku-4-5-20251001",
                "prompt_file": "writer.md",
                "tools": ["read_file", "write_file", "get_current_time"],
                "description": "Writing, editing, and file-based tasks",
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
            "webhook_url_env": "TELEGRAM_WEBHOOK_URL",
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
    "security": {"max_tool_calls_per_request": 15},
    "ui": {"port": 8000, "host": "0.0.0.0"},
}

_JOBS_TEMPLATE = {"jobs": []}

_ENV_EXAMPLE = """\
# Required
ANTHROPIC_API_KEY=your-anthropic-api-key
BRAVE_API_KEY=your-brave-search-api-key
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_WEBHOOK_URL=https://your-domain.com/webhook

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

    print("\nDone. Next steps:")
    print(f"  1. Edit {home / 'config.json'} — set your model preferences")
    print(f"  2. Copy {home / '.env.example'} → {home / '.env'} and fill in API keys")
    print("  3. Run: kore gateway")


def cmd_migrate() -> None:
    """Apply any pending migrations to ~/.kore. (Stub — nothing to migrate in Phase 1.)"""
    print("Nothing to migrate.")
