from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kore.config import KORE_HOME, KoreConfig
from kore.llm.types import KoreMessage

if TYPE_CHECKING:
    from kore.session.compactor import Compactor

logger = logging.getLogger(__name__)


def _sessions_dir() -> Path:
    return KORE_HOME / "workspace" / "sessions"


class SessionBuffer:
    """Manages a single session: load, append, compact, save."""

    def __init__(
        self,
        session_id: str,
        created_at: datetime,
        summary: str | None,
        turns: list[dict[str, Any]],
    ) -> None:
        self._session_id = session_id
        self._created_at = created_at
        self._summary = summary
        self._turns = turns

    @classmethod
    def load(cls, session_id: str) -> SessionBuffer:
        """Load session from disk. Creates a new empty session if file absent."""
        sess_dir = _sessions_dir()
        sess_dir.mkdir(parents=True, exist_ok=True)
        path = sess_dir / f"{session_id}.json"
        if not path.exists():
            return cls(session_id, datetime.now(timezone.utc), None, [])
        try:
            data = json.loads(path.read_text())
            return cls(
                session_id=data["session_id"],
                created_at=datetime.fromisoformat(data["created_at"]),
                summary=data.get("summary"),
                turns=data.get("turns", []),
            )
        except Exception:
            logger.warning("Corrupt session file %s — starting fresh", path)
            return cls(session_id, datetime.now(timezone.utc), None, [])

    def append(self, role: str, content: str) -> None:
        """Append a turn to the in-memory buffer."""
        self._turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def history(self) -> list[KoreMessage]:
        """Return summary block (if any) + all turns as KoreMessage list.

        The summary block's timestamp equals the oldest turn's timestamp so that
        the Pydantic AI history converter sees a monotonically increasing sequence.
        """
        messages: list[KoreMessage] = []
        if self._summary:
            if self._turns:
                ts = datetime.fromisoformat(self._turns[0]["timestamp"])
            else:
                ts = datetime.now(timezone.utc)
            messages.append(KoreMessage(
                role="assistant",
                content=f"[Session summary]\n{self._summary}",
                timestamp=ts,
            ))
        for t in self._turns:
            messages.append(KoreMessage(
                role=t["role"],
                content=t["content"],
                timestamp=datetime.fromisoformat(t["timestamp"]),
            ))
        return messages

    def _token_estimate(self) -> int:
        """Rough token estimate: total chars (turns + summary) divided by 4."""
        total = sum(len(t["content"]) for t in self._turns)
        total += len(self._summary or "")
        return total // 4

    async def compact_if_needed(
        self,
        config: KoreConfig,
        compactor: Compactor | None = None,
    ) -> None:
        """Compact old turns into summary if token estimate exceeds threshold."""
        if self._token_estimate() < config.session.compaction_token_threshold:
            return
        keep = config.session.keep_recent_turns
        old_turns = self._turns[:-keep] if len(self._turns) > keep else []
        if not old_turns:
            return
        if compactor is None:
            from kore.session.compactor import Compactor
            compactor = Compactor.from_config(config)
        try:
            self._summary = await compactor.summarise(self._summary, old_turns)
            self._turns = self._turns[-keep:]
        except Exception:
            logger.warning("Compaction failed — skipping this turn, buffer will grow")

    def save(self) -> None:
        """Write session to disk atomically via randomised .tmp → rename."""
        sess_dir = _sessions_dir()
        sess_dir.mkdir(parents=True, exist_ok=True)
        target = sess_dir / f"{self._session_id}.json"
        tmp = sess_dir / f"{self._session_id}.{uuid.uuid4().hex}.tmp"
        data: dict[str, Any] = {
            "session_id": self._session_id,
            "created_at": self._created_at.isoformat(),
            "summary": self._summary,
            "turns": self._turns,
        }
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(target)
