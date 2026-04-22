from __future__ import annotations

import pytest


# ── REST /api/sessions/{id}/trace ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_trace_returns_empty_when_store_is_none(kore_home):
    """GET /api/sessions/{id}/trace returns [] when trace_store is None."""
    from httpx import ASGITransport, AsyncClient
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config)  # no trace_store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/any_session/trace")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_session_trace_returns_persisted_events(kore_home, tmp_path):
    """GET /api/sessions/{id}/trace returns all events for the session."""
    from httpx import ASGITransport, AsyncClient
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app
    from kore.gateway.trace_store import TraceStore

    store = TraceStore(tmp_path / "kore.db")
    await store.add({"type": "session_start", "session_id": "s1", "ts": "t"})
    await store.add({"type": "session_done", "session_id": "s1", "ts": "t"})
    await store.add({"type": "session_start", "session_id": "s2", "ts": "t"})

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config, trace_store=store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/sessions/s1/trace")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["type"] == "session_start"
    assert data[1]["type"] == "session_done"


# ── Wiring ──────────────────────────────────────────────────────────────────


def test_create_app_with_trace_store_none_stores_none_in_state():
    """create_app(config) must set app.state.trace_store to None by default."""
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    app = create_app(config)
    assert app.state.trace_store is None


def test_create_app_with_trace_store_stores_instance(tmp_path):
    """create_app(config, trace_store=store) must store the instance in app.state."""
    from kore.config import KoreConfig, LLMConfig
    from kore.gateway.server import create_app
    from kore.gateway.trace_store import TraceStore

    config = KoreConfig(version="1.0.0", llm=LLMConfig(providers={}))
    store = TraceStore(tmp_path / "kore.db")
    app = create_app(config, trace_store=store)
    assert app.state.trace_store is store
