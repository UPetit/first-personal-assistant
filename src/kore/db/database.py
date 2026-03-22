from __future__ import annotations

from pathlib import Path

from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


_VEC_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS event_embeddings USING vec0(
    event_id  INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
"""


def create_engine(db_path: Path) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given SQLite path."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
    )
    _register_sqlite_extensions(engine)
    return engine


def _register_sqlite_extensions(engine: AsyncEngine) -> None:
    """Load sqlite-vec extension on every new connection (if available)."""

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _connect(dbapi_conn, _record):
        try:
            import sqlite_vec
            dbapi_conn.enable_load_extension(True)
            sqlite_vec.load(dbapi_conn)
            dbapi_conn.enable_load_extension(False)
        except Exception:
            pass  # sqlite-vec unavailable; vector search will be skipped gracefully


_DDL_STATEMENTS = [
    # Main events table
    """CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    category    TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    source      TEXT,
    importance  REAL    DEFAULT 0.5,
    embedding   BLOB,
    consolidated INTEGER DEFAULT 0,
    superseded_by INTEGER
)""",
    # FTS5 virtual table
    """CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content,
    content='events',
    content_rowid='id'
)""",
    # INSERT trigger
    """CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, content) VALUES (new.id, new.content);
END""",
    # DELETE trigger
    """CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.id, old.content);
END""",
    # UPDATE trigger
    """CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO events_fts(rowid, content) VALUES (new.id, new.content);
END""",
]

_VEC_DDL = """CREATE VIRTUAL TABLE IF NOT EXISTS event_embeddings USING vec0(
    event_id  INTEGER PRIMARY KEY,
    embedding FLOAT[384]
)"""


async def setup_schema(engine: AsyncEngine) -> None:
    """Create all tables, FTS5 virtual tables, triggers, and vec table if available."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        for stmt in _DDL_STATEMENTS:
            await conn.execute(text(stmt))

        # vec0 table requires sqlite-vec extension loaded — skip gracefully if absent
        try:
            await conn.execute(text(_VEC_DDL))
        except Exception:
            pass
