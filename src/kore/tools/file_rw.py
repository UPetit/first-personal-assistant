from __future__ import annotations

from pathlib import Path

from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
from kore.config import KORE_HOME
from kore.tools.registry import register

_MAX_READ_CHARS = 16_000
_MAX_WRITE_BYTES = 1_024 * 1_024  # 1 MB


def _safe_path(relative: str) -> Path:
    """Resolve path against sandbox, reject anything that escapes it."""
    base = (KORE_HOME / "workspace" / "files").resolve()
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Path escapes sandbox: {relative!r}")
    return resolved


async def read_file(ctx: RunContext[KoreDeps], path: str) -> str:
    """Read a file from the workspace. path is relative to ~/.kore/workspace/files/.

    Returns [FILE_CONTENT] tagged text. Truncates at 16,000 chars.
    Returns [FILE_CONTENT]\\n[Error: ...] on failure — does not raise.
    """
    try:
        safe = _safe_path(path)
        text = safe.read_text()[:_MAX_READ_CHARS]
        return f"[FILE_CONTENT]\n{text}"
    except Exception as exc:
        return f"[FILE_CONTENT]\n[Error: {exc}]"


async def write_file(ctx: RunContext[KoreDeps], path: str, content: str) -> str:
    """Write content to a file in the workspace. path is relative to ~/.kore/workspace/files/.

    Creates parent directories automatically (within sandbox).
    Rejects files over 1 MB.
    Returns confirmation string or [Error: ...] on failure — does not raise.
    """
    try:
        safe = _safe_path(path)
        if len(content.encode()) > _MAX_WRITE_BYTES:
            return f"[Error: content exceeds 1 MB limit ({len(content.encode())} bytes)]"
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as exc:
        return f"[Error: {exc}]"


register("read_file", read_file)
register("write_file", write_file)
