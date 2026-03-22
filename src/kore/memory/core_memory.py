from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


class TokenCapExceeded(Exception):
    """Raised when a core memory update would exceed the token cap."""


class CoreMemory:
    """Layer 1 memory: structured JSON always injected into every agent prompt.

    Enforces a configurable token cap (default 4,000 tokens approximated as
    ``len(json_bytes) // 4``). Updates are atomic: if the cap would be exceeded
    after a write, the change is rolled back and ``TokenCapExceeded`` is raised.
    """

    def __init__(self, path: Path, max_tokens: int = 4000) -> None:
        self._path = path
        self._max_tokens = max_tokens
        self._data: dict[str, Any] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def get(self) -> dict[str, Any]:
        """Return a shallow copy of the current core memory dict."""
        return dict(self._data)

    def update(self, path: str, value: Any) -> None:
        """Set *value* at dot-notation *path*, creating intermediate dicts as needed.

        Raises :class:`TokenCapExceeded` if the update would exceed the token cap;
        the store is left unchanged in that case.
        """
        backup = copy.deepcopy(self._data)
        parent, key = self._navigate(path)
        parent[key] = value
        new_size = self._count_tokens()
        if new_size > self._max_tokens:
            self._data = backup
            raise TokenCapExceeded(
                f"Update to {path!r} would exceed the {self._max_tokens}-token cap "
                f"(would be {new_size} tokens)."
            )
        self._save()

    def delete(self, path: str) -> None:
        """Delete the key at dot-notation *path*. No-op if the path does not exist."""
        parts = path.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                return  # path doesn't exist — no-op
            current = current[part]
        current.pop(parts[-1], None)
        self._save()

    def format_for_prompt(self) -> str:
        """Return a Markdown-formatted string suitable for injection into a prompt."""
        if not self._data:
            return "(core memory is empty)"
        return "```json\n" + json.dumps(self._data, indent=2) + "\n```"

    # ── internals ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def _count_tokens(self) -> int:
        """Approximate token count: len(JSON bytes) // 4."""
        return len(json.dumps(self._data).encode()) // 4

    def _navigate(self, path: str) -> tuple[dict[str, Any], str]:
        """Walk dot-notation *path*, creating intermediate dicts as needed.

        Returns (parent_dict, final_key).
        """
        parts = path.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        return current, parts[-1]
