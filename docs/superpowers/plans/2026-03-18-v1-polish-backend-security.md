# v1 Polish — Backend & Security Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the v1 backend with SSRF prevention in the scrape tool, exception detail sanitization in API routes, query parameter bounds on `/api/logs`, and debug logging for Telegram auth rejections.

**Architecture:** Four independent, targeted fixes across three files. Each task follows TDD — tests written first, then implementation. No new modules created. A1 is the most complex (SSRF redirect handling); A2/A3 are surgical edits to `routes_api.py`; A4 is a one-method change in `telegram.py`.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio, respx (HTTP mocking), stdlib `socket` + `ipaddress` (SSRF), FastAPI `Query`, structlog-compatible JSON logging already configured.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `src/kore/tools/scrape.py` | Modify | Add `_check_url()` SSRF validator, manual redirect loop |
| `src/kore/gateway/routes_api.py` | Modify | Add `request_id`, sanitize exceptions, add `Query` bounds on `n` |
| `src/kore/channels/telegram.py` | Modify | Debug log in `_is_allowed()` |
| `tests/test_tools.py` | Modify | Append SSRF tests |
| `tests/test_gateway.py` | Modify | Append exception sanitization + query bounds tests |
| `tests/test_telegram.py` | Modify | Append rejection logging test |

---

## Task 1: SSRF Prevention in `scrape.py`

**Files:**
- Modify: `src/kore/tools/scrape.py`
- Test: `tests/test_tools.py` (append)

### Context

`scrape_url` currently calls `httpx.AsyncClient(follow_redirects=True, ...)` with no URL validation. An adversarial web page or prompt injection could instruct the agent to scrape `http://169.254.169.254/latest/meta-data/` to exfiltrate cloud metadata.

The fix adds a `_check_url(url)` helper that:
1. Rejects non-http/https schemes
2. Resolves the hostname and rejects private/loopback IPs
3. Replaces automatic redirect following with a manual loop (max 3 hops), re-validating each hop

SSRF error strings do NOT get the `[EXTERNAL_CONTENT]` prefix — that prefix is added only after a successful fetch. HTTP errors after a successful network response still get `[EXTERNAL_CONTENT]` (existing behaviour preserved).

---

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tools.py`:

```python
# ── scrape_url SSRF prevention ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scrape_url_rejects_ftp_scheme(mock_deps):
    from kore.tools.scrape import scrape_url
    result = await scrape_url(mock_deps, "ftp://example.com/file")
    assert result == "[Error: Blocked — only http/https URLs are allowed]"
    assert "[EXTERNAL_CONTENT]" not in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_private_10_block(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("10.0.0.1", 0))],
    )
    result = await scrape_url(mock_deps, "http://internal.corp/api")
    assert "[Error: Blocked" in result
    assert "[EXTERNAL_CONTENT]" not in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_private_172_16_block(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("172.16.0.1", 0))],
    )
    result = await scrape_url(mock_deps, "http://internal.corp/api")
    assert "[Error: Blocked" in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_private_192_168_block(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("192.168.1.1", 0))],
    )
    result = await scrape_url(mock_deps, "http://internal.corp/api")
    assert "[Error: Blocked" in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_loopback(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    result = await scrape_url(mock_deps, "http://localhost/admin")
    assert "[Error: Blocked" in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_link_local_169(mock_deps, monkeypatch):
    """169.254.169.254 is the AWS/GCP metadata endpoint — must be blocked."""
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("169.254.169.254", 0))],
    )
    result = await scrape_url(mock_deps, "http://metadata.internal/")
    assert "[Error: Blocked" in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_ipv6_loopback(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("::1", 0))],
    )
    result = await scrape_url(mock_deps, "http://ipv6-internal/")
    assert "[Error: Blocked" in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_ipv6_ula(mock_deps, monkeypatch):
    """fc00::/7 (IPv6 Unique Local Addresses) must be blocked."""
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("fc00::1", 0))],
    )
    result = await scrape_url(mock_deps, "http://ipv6-ula-host/")
    assert "[Error: Blocked" in result


@pytest.mark.asyncio
@respx.mock
async def test_scrape_url_redirect_to_private_blocked(mock_deps, monkeypatch):
    """Redirect to a private IP must be blocked even if origin was public."""
    from kore.tools.scrape import scrape_url

    def mock_getaddrinfo(host, port, *args, **kwargs):
        if host == "internal.corp":
            return [(None, None, None, None, ("192.168.1.1", 0))]
        return [(None, None, None, None, ("93.184.216.34", 0))]  # public IP

    monkeypatch.setattr("socket.getaddrinfo", mock_getaddrinfo)
    respx.get("http://example.com/page").mock(
        return_value=httpx.Response(301, headers={"location": "http://internal.corp/secret"})
    )
    result = await scrape_url(mock_deps, "http://example.com/page")
    assert "[Error: Blocked" in result
    assert "[EXTERNAL_CONTENT]" not in result


@pytest.mark.asyncio
@respx.mock
async def test_scrape_url_redirect_limit_enforced(mock_deps, monkeypatch):
    """A 4th redirect hop must be refused with a 'too many redirects' error."""
    from kore.tools.scrape import scrape_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    # Chain: /a → /b → /c → /d → /e (4th redirect, should be blocked)
    respx.get("http://example.com/a").mock(return_value=httpx.Response(302, headers={"location": "http://example.com/b"}))
    respx.get("http://example.com/b").mock(return_value=httpx.Response(302, headers={"location": "http://example.com/c"}))
    respx.get("http://example.com/c").mock(return_value=httpx.Response(302, headers={"location": "http://example.com/d"}))
    respx.get("http://example.com/d").mock(return_value=httpx.Response(302, headers={"location": "http://example.com/e"}))
    result = await scrape_url(mock_deps, "http://example.com/a")
    assert result == "[Error: Too many redirects]"


@pytest.mark.asyncio
@respx.mock
async def test_scrape_url_valid_public_url_succeeds(mock_deps, monkeypatch):
    """A valid public URL with a public IP resolves normally."""
    from kore.tools.scrape import scrape_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    html = "<html><body><article><p>Public content here.</p></article></body></html>"
    respx.get("https://example.com/article").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    result = await scrape_url(mock_deps, "https://example.com/article")
    assert result.startswith("[EXTERNAL_CONTENT]")
    assert "Public content" in result
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_tools.py -k "ssrf or redirect_limit or valid_public" -v 2>&1 | tail -20
```

Expected: all new tests FAIL with `AssertionError` (SSRF checks don't exist yet).

- [ ] **Step 3: Update existing `scrape_url` tests to monkeypatch DNS**

After the implementation, `_check_url()` calls `socket.getaddrinfo` before making any HTTP request. The three existing tests (`test_scrape_url_extracts_content`, `test_scrape_url_truncates`, `test_scrape_url_fetch_error`) do not monkeypatch DNS — they will fail in environments without internet access (or if `example.com` resolves to an unexpected IP). Update all three to add the DNS monkeypatch.

In `tests/test_tools.py`, update the three existing scrape tests:

- `test_scrape_url_extracts_content` — add `monkeypatch` parameter and `monkeypatch.setattr("socket.getaddrinfo", lambda h, p, *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))])` before the `respx.get(...)` call.
- `test_scrape_url_truncates` — same.
- `test_scrape_url_fetch_error` — same.

The updated `test_scrape_url_extracts_content` should look like:

```python
@pytest.mark.asyncio
@respx.mock
async def test_scrape_url_extracts_content(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    html = (
        "<html><body>"
        "<article><p>Hello world content here.</p></article>"
        "</body></html>"
    )
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    result = await scrape_url(mock_deps, "https://example.com/page")
    assert result.startswith("[EXTERNAL_CONTENT]")
    assert "Hello world" in result
```

Apply the same `monkeypatch` parameter + `setattr` pattern to the other two tests.

- [ ] **Step 4: Implement SSRF prevention in `src/kore/tools/scrape.py`**

Replace the entire file with:

```python
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from pydantic_ai import RunContext

from kore.tools.registry import register

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_MAX_CHARS = 8_000
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _check_url(url: str) -> str | None:
    """Validate *url* for SSRF. Returns an error string on failure, None if safe.

    Checks:
    - Only http/https schemes are allowed.
    - The resolved IP must not be private, loopback, link-local, or reserved.

    The [EXTERNAL_CONTENT] prefix is NOT included in error returns — it is
    only added after a successful HTTP fetch.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return f"[Error: Invalid URL — {exc}]"

    if parsed.scheme not in ("http", "https"):
        return "[Error: Blocked — only http/https URLs are allowed]"

    hostname = parsed.hostname
    if not hostname:
        return "[Error: Invalid URL — missing hostname]"

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return f"[Error: DNS resolution failed — {exc}]"

    for addr_info in addr_infos:
        ip_str = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            return "[Error: Blocked — private/internal URL]"

    return None


async def scrape_url(ctx: RunContext, url: str) -> str:
    """Fetch and extract readable text from a URL. Returns [EXTERNAL_CONTENT] tagged text.

    The [EXTERNAL_CONTENT] prefix is a prompt-injection defence — it signals to the
    agent that this content came from an untrusted external source.

    SSRF protection: rejects private/loopback IPs and non-http/https schemes.
    Follows up to 3 redirects (301/302/303/307/308), re-validating each hop.
    """
    err = _check_url(url)
    if err:
        return err

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=15.0) as client:
            current_url = url
            for hop in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url, headers={"User-Agent": _USER_AGENT})
                if response.status_code not in _REDIRECT_STATUSES:
                    response.raise_for_status()
                    html = response.text
                    break
                # It's a redirect — check the hop limit before following
                if hop >= _MAX_REDIRECTS:
                    return "[Error: Too many redirects]"
                location = response.headers.get("location", "")
                if not location:
                    return "[Error: Redirect missing Location header]"
                # Resolve relative redirect URLs against the current URL
                location = urljoin(current_url, location)
                err = _check_url(location)
                if err:
                    return err
                current_url = location
            else:
                return "[Error: Too many redirects]"
    except Exception as exc:
        return f"[EXTERNAL_CONTENT]\n[Error: {exc}]"

    extracted = trafilatura.extract(html) or ""
    if not extracted:
        return f"[EXTERNAL_CONTENT]\n[Error: could not extract content from {url!r}]"

    if len(extracted) > _MAX_CHARS:
        extracted = extracted[:_MAX_CHARS]

    return f"[EXTERNAL_CONTENT]\n{extracted}"


register("scrape_url", scrape_url)
```

- [ ] **Step 5: Run new SSRF tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_tools.py -k "ssrf or redirect_limit or valid_public or rejects or ula" -v
```

Expected: all new SSRF tests PASS (12 new tests).

- [ ] **Step 6: Run full tools test suite (no regressions)**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_tools.py -v
```

Expected: all existing tests still PASS (scrape_url_extracts_content, truncates, fetch_error — now with monkeypatched DNS).

- [ ] **Step 7: Commit**

```bash
cd /root/kore-ai
git add src/kore/tools/scrape.py tests/test_tools.py
git commit -m "feat: SSRF prevention in scrape_url — scheme check, private IP rejection, redirect validation"
```

---

## Task 2: Exception Detail Sanitization in `routes_api.py`

**Files:**
- Modify: `src/kore/gateway/routes_api.py`
- Test: `tests/test_gateway.py` (append)

### Context

`POST /api/message`, `PUT /api/memory`, and `DELETE /api/memory` currently return `str(exc)` directly in HTTP responses, which can leak internal paths, config details, or stack frames. The fix returns a generic `{"detail": "Operation failed", "request_id": "<8-char-hex>"}` so callers can correlate with server logs without exposing internals.

Status code change: `PUT /api/memory` and `DELETE /api/memory` currently return 400. They are intentionally changed to 500 because errors at the memory layer are unexpected server-side failures, not malformed client input.

---

- [ ] **Step 1: Write failing tests**

Append to `tests/test_gateway.py`:

```python
# ── exception sanitization ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_message_exception_returns_sanitized_500():
    """POST /api/message exception must not leak the raw error message."""
    from unittest.mock import AsyncMock
    from kore.llm.types import AgentResponse

    mock_orch = MagicMock()
    mock_orch.run = AsyncMock(side_effect=RuntimeError("internal secret path: /etc/kore/keys"))

    app = _make_app(_make_config(auth_enabled=False), orchestrator=mock_orch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/message", json={"text": "hi"})

    assert r.status_code == 500
    body = r.json()
    assert "detail" in body["detail"]
    assert "request_id" in body["detail"]
    assert "secret" not in r.text
    assert "internal" not in r.text


@pytest.mark.asyncio
async def test_put_memory_exception_returns_sanitized_500():
    """PUT /api/memory exception must return 500 with request_id, not raw error."""
    core_memory = MagicMock()
    core_memory.update.side_effect = RuntimeError("db path leaked: /home/user/.kore/kore.db")

    app = _make_app_with_components(core_memory=core_memory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(
            "/api/memory",
            json={"path": "user.name", "value": "Bob"},
            auth=("admin", "secret"),
        )

    assert r.status_code == 500
    body = r.json()
    assert "detail" in body["detail"]
    assert "request_id" in body["detail"]
    assert "db path" not in r.text


@pytest.mark.asyncio
async def test_delete_memory_exception_returns_sanitized_500():
    """DELETE /api/memory exception must return 500 with request_id, not raw error."""
    core_memory = MagicMock()
    core_memory.delete.side_effect = KeyError("secret_key")

    app = _make_app_with_components(core_memory=core_memory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete("/api/memory/user.name", auth=("admin", "secret"))

    assert r.status_code == 500
    body = r.json()
    assert "detail" in body["detail"]
    assert "request_id" in body["detail"]
    assert "secret_key" not in r.text
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "sanitized" -v 2>&1 | tail -15
```

Expected: FAIL — currently returns 400/500 with raw `str(exc)`.

- [ ] **Step 3: Implement exception sanitization in `src/kore/gateway/routes_api.py`**

**3a.** Update the imports at the top of the file:

*Before (line 1-10):*
```python
from __future__ import annotations

from typing import Any

from apscheduler.jobstores.base import JobLookupError as APJobLookupError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from kore.gateway.auth import require_auth
```

*After:*
```python
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from apscheduler.jobstores.base import JobLookupError as APJobLookupError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from kore.gateway.auth import require_auth

logger = logging.getLogger(__name__)
```

**3b.** Replace `update_memory` handler (lines 102–115):

*Before:*
```python
@router.put("/memory")
async def update_memory(
    body: UpdateMemoryRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    try:
        cm.update(body.path, body.value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "updated", "path": body.path}
```

*After:*
```python
@router.put("/memory")
async def update_memory(
    body: UpdateMemoryRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    request_id = uuid4().hex[:8]
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    try:
        cm.update(body.path, body.value)
    except Exception:
        logger.exception("update_memory error", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"detail": "Operation failed", "request_id": request_id},
        )
    return {"status": "updated", "path": body.path}
```

**3c.** Replace `delete_memory` handler (lines 118–131):

*Before:*
```python
@router.delete("/memory/{path:path}")
async def delete_memory(
    path: str,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    try:
        cm.delete(path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted", "path": path}
```

*After:*
```python
@router.delete("/memory/{path:path}")
async def delete_memory(
    path: str,
    request: Request,
    _: str = Depends(require_auth),
) -> dict[str, str]:
    request_id = uuid4().hex[:8]
    cm = request.app.state.core_memory
    if cm is None:
        raise HTTPException(status_code=503, detail="Memory not available")
    try:
        cm.delete(path)
    except Exception:
        logger.exception("delete_memory error", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"detail": "Operation failed", "request_id": request_id},
        )
    return {"status": "deleted", "path": path}
```

**3d.** Replace `post_message` handler (lines 157–170):

*Before:*
```python
@router.post("/message", response_model=MessageResponse)
async def post_message(
    body: MessageRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> MessageResponse:
    orchestrator = request.app.state.orchestrator
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available")
    try:
        response = await orchestrator.run(body.text, body.session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MessageResponse(response=response.content, session_id=body.session_id)
```

*After:*
```python
@router.post("/message", response_model=MessageResponse)
async def post_message(
    body: MessageRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> MessageResponse:
    request_id = uuid4().hex[:8]
    orchestrator = request.app.state.orchestrator
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not available")
    try:
        response = await orchestrator.run(body.text, body.session_id)
    except Exception:
        logger.exception("post_message error", extra={"request_id": request_id})
        raise HTTPException(
            status_code=500,
            detail={"detail": "Operation failed", "request_id": request_id},
        )
    return MessageResponse(response=response.content, session_id=body.session_id)
```

- [ ] **Step 4: Run sanitization tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "sanitized" -v
```

Expected: all 3 new tests PASS.

- [ ] **Step 5: Run full gateway test suite (no regressions)**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -v 2>&1 | tail -20
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
cd /root/kore-ai
git add src/kore/gateway/routes_api.py tests/test_gateway.py
git commit -m "fix: sanitize exception details in API responses — request_id + generic message"
```

---

## Task 3: `/api/logs` Query Parameter Bounds

**Files:**
- Modify: `src/kore/gateway/routes_api.py`
- Test: `tests/test_gateway.py` (append)

### Context

`GET /api/logs?n=<int>` has no validation. Passing `n=0` or `n=9999999` could cause degenerate behaviour. The fix constrains `n` to `[1, 1000]` using FastAPI's `Query` (already added to imports in Task 2).

---

- [ ] **Step 1: Write failing tests**

Append to `tests/test_gateway.py`:

```python
# ── /api/logs query param bounds ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_logs_n_zero_returns_422():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=0", auth=("admin", "secret"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_logs_n_too_large_returns_422():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=1001", auth=("admin", "secret"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_logs_valid_n_returns_200():
    app = _make_app_with_components()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/logs?n=50", auth=("admin", "secret"))
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "logs_n" -v 2>&1 | tail -10
```

Expected: `test_get_logs_n_zero_returns_422` and `test_get_logs_n_too_large_returns_422` FAIL (currently return 200).

- [ ] **Step 3: Apply the query bounds fix in `src/kore/gateway/routes_api.py`**

`Query` is already imported (done in Task 2). Change the `get_logs` handler signature:

*Before (line 136–142):*
```python
@router.get("/logs")
async def get_logs(
    request: Request,
    n: int = 100,
    _: str = Depends(require_auth),
) -> list[str]:
    return request.app.state.log_handler.recent(n)
```

*After:*
```python
@router.get("/logs")
async def get_logs(
    request: Request,
    n: int = Query(default=100, ge=1, le=1000),
    _: str = Depends(require_auth),
) -> list[str]:
    return request.app.state.log_handler.recent(n)
```

- [ ] **Step 4: Run logs bounds tests**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -k "logs_n" -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Run full gateway suite**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_gateway.py -v 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /root/kore-ai
git add src/kore/gateway/routes_api.py tests/test_gateway.py
git commit -m "fix: bound /api/logs?n to [1, 1000] via FastAPI Query"
```

---

## Task 4: Telegram Rejection Logging

**Files:**
- Modify: `src/kore/channels/telegram.py`
- Test: `tests/test_telegram.py` (append)

### Context

When `_is_allowed()` returns `False`, the message is silently dropped. Adding a `DEBUG` log inside `_is_allowed()` covers all 5 call sites (messages, /status, /jobs, /memory, /cancel) in one change and creates an audit trail for unexpected access attempts.

---

- [ ] **Step 1: Write failing test**

First, verify `tests/test_telegram.py` has `import logging` at the top. If it does not, add it alongside the existing imports.

Append to `tests/test_telegram.py`:

```python
# ── rejection logging ─────────────────────────────────────────────────────────

def test_is_allowed_logs_rejection_at_debug(caplog):
    """Rejecting an unknown user_id must emit a DEBUG log."""
    channel = _make_channel([111, 222])
    with caplog.at_level(logging.DEBUG, logger="kore.channels.telegram"):
        result = channel._is_allowed(999)
    assert result is False
    assert any("999" in record.message for record in caplog.records)
    assert any(record.levelno == logging.DEBUG for record in caplog.records)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_telegram.py -k "logs_rejection" -v 2>&1 | tail -10
```

Expected: FAIL — no debug log emitted yet.

- [ ] **Step 3: Update `_is_allowed()` in `src/kore/channels/telegram.py`**

*Before (lines 91–94):*
```python
def _is_allowed(self, user_id: int) -> bool:
    if not self._config.allowed_user_ids:
        return True
    return user_id in self._config.allowed_user_ids
```

*After:*
```python
def _is_allowed(self, user_id: int) -> bool:
    if not self._config.allowed_user_ids:
        return True
    allowed = user_id in self._config.allowed_user_ids
    if not allowed:
        logger.debug("Rejected message from unauthorized user_id=%s", user_id)
    return allowed
```

- [ ] **Step 4: Run rejection logging test**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_telegram.py -k "logs_rejection" -v
```

Expected: PASS.

- [ ] **Step 5: Run full telegram suite (no regressions)**

```bash
cd /root/kore-ai && python3 -m pytest tests/test_telegram.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run full suite**

```bash
cd /root/kore-ai && python3 -m pytest --tb=short -q
```

Expected: all tests PASS. Record final count (should be ≥ 268: 256 existing + 10 SSRF + 3 sanitization + 3 logs bounds + 1 rejection log = 273).

- [ ] **Step 7: Commit**

```bash
cd /root/kore-ai
git add src/kore/channels/telegram.py tests/test_telegram.py
git commit -m "fix: log debug message when Telegram user rejected by allowlist"
```

---

## Verification Checklist

After all four tasks:

- [ ] `python3 -m pytest --tb=short -q` — green, ≥ 268 tests
- [ ] `tests/test_tools.py` — SSRF tests all pass (scheme, private IPs, redirect limit, redirect-to-private)
- [ ] `tests/test_gateway.py` — sanitization tests pass (no raw exception in response body), logs bounds tests pass (422/422/200)
- [ ] `tests/test_telegram.py` — rejection logging test passes
- [ ] `src/kore/tools/scrape.py` — `_check_url()` present, `follow_redirects=False`, manual redirect loop
- [ ] `src/kore/gateway/routes_api.py` — `from uuid import uuid4` imported, `Query` imported, `request_id` in all 3 exception handlers, `GET /api/logs` uses `Query(ge=1, le=1000)`
- [ ] `src/kore/channels/telegram.py` — `_is_allowed()` logs at DEBUG when rejecting
- [ ] No regressions in any previously-passing tests
