from __future__ import annotations

import asyncio
import shlex

from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
from kore.tools.registry import register

_DEFAULT_TIMEOUT = 60  # seconds


async def run_command(ctx: RunContext[KoreDeps], command: str) -> str:
    """Run an allowed shell command and return its output.

    Only binaries listed in this executor's shell_allowlist may be invoked.
    The first token of *command* is matched against the allowlist by name
    (path components are stripped, so '/usr/local/bin/summarize' matches 'summarize').
    """
    allowlist = ctx.deps.shell_allowlist
    if not allowlist:
        return "[Error: shell command execution is disabled for this executor — shell_allowlist is empty]"

    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return f"[Error: could not parse command: {exc}]"

    if not tokens:
        return "[Error: empty command]"

    binary = tokens[0].split("/")[-1]  # strip path, keep name
    if binary not in allowlist:
        return f"[Error: '{binary}' is not in this executor's shell_allowlist {allowlist}]"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        return f"[Error: command timed out after {_DEFAULT_TIMEOUT}s]"
    except Exception as exc:
        return f"[Error: failed to run command: {exc}]"

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()

    if proc.returncode != 0:
        parts = [f"[Exit code {proc.returncode}]"]
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr] {err}")
        return "\n".join(parts)

    return out or err or "[command produced no output]"


register("run_command", run_command)
