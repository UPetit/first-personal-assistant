from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx
from pydantic import SecretStr

from kore.config import KoreConfig, LLMConfig, ToolConfig
from kore.tools.registry import all_tools, get_tools


# --- Registry ---

def test_registry_unknown_tool_raises():
    with pytest.raises(KeyError, match="nonexistent"):
        get_tools(["nonexistent"])


def test_registry_known_tools_returns_callables():
    # Import tool modules to trigger their self-registration
    import kore.tools.time_tool  # noqa: F401
    import kore.tools.scrape     # noqa: F401
    import kore.tools.web_search  # noqa: F401

    tools = get_tools(["get_current_time", "scrape_url", "web_search"])
    assert len(tools) == 3
    assert all(callable(t) for t in tools)


def test_registry_wildcard_returns_all_tools():
    import kore.tools.time_tool   # noqa: F401
    import kore.tools.scrape      # noqa: F401
    import kore.tools.web_search  # noqa: F401

    tools = get_tools(["*"])
    registered = all_tools()
    assert len(tools) == len(registered)
    assert set(tools) == set(registered.values())


def test_registry_wildcard_rejects_mixed_names():
    with pytest.raises(ValueError, match="Wildcard"):
        get_tools(["*", "get_current_time"])


# --- get_current_time ---

@pytest.mark.asyncio
async def test_get_current_time_format(mock_deps):
    from kore.tools.time_tool import get_current_time
    result = await get_current_time(mock_deps)   # mock_deps stands in for RunContext
    # Must parse as valid ISO 8601 with timezone
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


# --- scrape_url ---

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


@pytest.mark.asyncio
@respx.mock
async def test_scrape_url_truncates(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    # Build HTML with content well above 8000 chars after trafilatura extraction.
    # "word " * 4_000 = ~20,000 chars raw; trafilatura will extract most of it.
    long_text = "word " * 4_000
    html = f"<html><body><article><p>{long_text}</p></article></body></html>"
    respx.get("https://example.com/long").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    result = await scrape_url(mock_deps, "https://example.com/long")
    prefix = "[EXTERNAL_CONTENT]\n"
    body = result[len(prefix):]
    assert len(body) <= 8_000


@pytest.mark.asyncio
@respx.mock
async def test_scrape_url_fetch_error(mock_deps, monkeypatch):
    from kore.tools.scrape import scrape_url

    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    respx.get("https://example.com/missing").mock(
        return_value=httpx.Response(404)
    )
    result = await scrape_url(mock_deps, "https://example.com/missing")
    assert result.startswith("[EXTERNAL_CONTENT]")
    assert "[Error:" in result


# --- web_search ---

_BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@pytest.mark.asyncio
@respx.mock
async def test_web_search_returns_results(mock_deps):
    from kore.tools.web_search import web_search

    respx.get(_BRAVE_WEB_SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Test Title",
                            "url": "https://example.com",
                            "description": "A useful snippet.",
                            "extra_snippets": ["More detail here.", "And here."],
                        }
                    ]
                }
            },
        )
    )
    results = await web_search(mock_deps, "test query")
    assert len(results) == 1
    assert results[0]["url"] == "https://example.com"
    assert results[0]["title"] == "Test Title"
    assert results[0]["description"] == "A useful snippet."
    assert results[0]["extra_snippets"] == ["More detail here.", "And here."]
    # Verify the request was sent with correct auth and query param
    last_req = respx.calls.last.request
    assert last_req.headers["X-Subscription-Token"] == "test-brave-key"
    assert "q=test+query" in str(last_req.url) or "q=test%20query" in str(last_req.url)


@pytest.mark.asyncio
@respx.mock
async def test_web_search_http_error(mock_deps):
    from kore.tools.web_search import web_search

    respx.get(_BRAVE_WEB_SEARCH_URL).mock(return_value=httpx.Response(500))
    results = await web_search(mock_deps, "test query")
    assert len(results) == 1
    assert "error" in results[0]


@pytest.mark.asyncio
@respx.mock
async def test_web_search_timeout(mock_deps):
    from kore.tools.web_search import web_search

    respx.get(_BRAVE_WEB_SEARCH_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    results = await web_search(mock_deps, "test query")
    assert len(results) == 1
    assert "error" in results[0]


# --- read_file / write_file ---

@pytest.fixture
def file_sandbox(tmp_path, monkeypatch):
    """Monkeypatch KORE_HOME to tmp_path for file I/O sandbox tests."""
    import kore.tools.file_rw as file_rw_mod
    import kore.config as config_mod
    monkeypatch.setattr(config_mod, "KORE_HOME", tmp_path)
    monkeypatch.setattr(file_rw_mod, "KORE_HOME", tmp_path)
    (tmp_path / "workspace" / "files").mkdir(parents=True)
    return tmp_path


@pytest.mark.asyncio
async def test_read_file_returns_content(file_sandbox, mock_deps):
    from kore.tools.file_rw import read_file
    (file_sandbox / "workspace" / "files" / "hello.txt").write_text("hello world")
    result = await read_file(mock_deps, "hello.txt")
    assert result.startswith("[FILE_CONTENT]")
    assert "hello world" in result


@pytest.mark.asyncio
async def test_read_file_truncates(file_sandbox, mock_deps):
    from kore.tools.file_rw import read_file
    big = "x" * 20_000
    (file_sandbox / "workspace" / "files" / "big.txt").write_text(big)
    result = await read_file(mock_deps, "big.txt")
    prefix = "[FILE_CONTENT]\n"
    body = result[len(prefix):]
    assert len(body) <= 16_000


@pytest.mark.asyncio
async def test_read_file_missing(file_sandbox, mock_deps):
    from kore.tools.file_rw import read_file
    result = await read_file(mock_deps, "nonexistent.txt")
    assert result.startswith("[FILE_CONTENT]")
    assert "[Error:" in result


@pytest.mark.asyncio
async def test_write_file_creates_file(file_sandbox, mock_deps):
    from kore.tools.file_rw import write_file
    result = await write_file(mock_deps, "output.txt", "hello")
    assert "output.txt" in result or "Written" in result
    assert (file_sandbox / "workspace" / "files" / "output.txt").read_text() == "hello"


@pytest.mark.asyncio
async def test_write_file_creates_dirs(file_sandbox, mock_deps):
    from kore.tools.file_rw import write_file
    result = await write_file(mock_deps, "subdir/nested/file.txt", "content")
    assert "[Error:" not in result
    assert (file_sandbox / "workspace" / "files" / "subdir" / "nested" / "file.txt").exists()


@pytest.mark.asyncio
async def test_write_file_too_large(file_sandbox, mock_deps):
    from kore.tools.file_rw import write_file
    big = "x" * (1024 * 1024 + 1)
    result = await write_file(mock_deps, "big.txt", big)
    assert "[Error:" in result


@pytest.mark.asyncio
async def test_path_traversal_rejected_read(file_sandbox, mock_deps):
    from kore.tools.file_rw import read_file
    result = await read_file(mock_deps, "../../config.json")
    assert "[Error:" in result


@pytest.mark.asyncio
async def test_path_traversal_rejected_write(file_sandbox, mock_deps):
    from kore.tools.file_rw import write_file
    result = await write_file(mock_deps, "../../evil.sh", "rm -rf /")
    assert "[Error:" in result


@pytest.mark.asyncio
async def test_symlink_escape_rejected(file_sandbox, mock_deps):
    from kore.tools.file_rw import read_file
    import os
    # Create a symlink inside sandbox pointing to /etc/hosts
    link = file_sandbox / "workspace" / "files" / "escape_link"
    try:
        os.symlink("/etc/hosts", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    result = await read_file(mock_deps, "escape_link")
    # _safe_path resolves the symlink via .resolve(), which follows the link to
    # /etc/hosts — outside the sandbox — so the path check must reject it.
    assert "[Error:" in result


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


@pytest.mark.asyncio
async def test_scrape_url_rejects_file_scheme(mock_deps):
    from kore.tools.scrape import scrape_url
    result = await scrape_url(mock_deps, "file:///etc/passwd")
    assert result == "[Error: Blocked — only http/https URLs are allowed]"
    assert "[EXTERNAL_CONTENT]" not in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_ip_literal_private(mock_deps, monkeypatch):
    """http://10.0.0.1/ (IP literal) must be blocked — no DNS needed."""
    from kore.tools.scrape import scrape_url
    # getaddrinfo on an IP literal returns that exact IP
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("10.0.0.1", 0))],
    )
    result = await scrape_url(mock_deps, "http://10.0.0.1/secret")
    assert "[Error: Blocked" in result
    assert "[EXTERNAL_CONTENT]" not in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_empty_addr_infos(mock_deps, monkeypatch):
    """If getaddrinfo returns empty list, treat as DNS failure."""
    from kore.tools.scrape import scrape_url
    monkeypatch.setattr("socket.getaddrinfo", lambda h, p, *a, **kw: [])
    result = await scrape_url(mock_deps, "http://ghost.corp/")
    assert "[Error: DNS resolution failed" in result
    assert "[EXTERNAL_CONTENT]" not in result


@pytest.mark.asyncio
async def test_scrape_url_rejects_unparseable_ip(mock_deps, monkeypatch):
    """If getaddrinfo returns an unparseable IP string, treat as blocked."""
    from kore.tools.scrape import scrape_url
    # Simulate getaddrinfo returning a non-IP string (e.g. a Unix socket path)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda h, p, *a, **kw: [(None, None, None, None, ("/var/run/something", 0))],
    )
    result = await scrape_url(mock_deps, "http://ghost.corp/")
    assert "[Error: Blocked" in result
    assert "[EXTERNAL_CONTENT]" not in result


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------

def _shell_deps(allowlist: list[str], base_deps):
    """Return a mock deps namespace with the given shell_allowlist."""
    from types import SimpleNamespace
    from kore.agents.deps import KoreDeps
    deps = KoreDeps(config=base_deps.deps.config, shell_allowlist=allowlist)
    return SimpleNamespace(deps=deps)


@pytest.mark.asyncio
async def test_run_command_allowed(mock_deps):
    from kore.tools.shell import run_command
    ctx = _shell_deps(["echo"], mock_deps)
    result = await run_command(ctx, "echo hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_run_command_blocked(mock_deps):
    from kore.tools.shell import run_command
    ctx = _shell_deps(["echo"], mock_deps)
    result = await run_command(ctx, "ls /tmp")
    assert "not in this executor's shell_allowlist" in result


@pytest.mark.asyncio
async def test_run_command_no_allowlist(mock_deps):
    from kore.tools.shell import run_command
    ctx = _shell_deps([], mock_deps)
    result = await run_command(ctx, "echo hi")
    assert "disabled for this executor" in result


@pytest.mark.asyncio
async def test_run_command_nonzero_exit(mock_deps):
    from kore.tools.shell import run_command
    ctx = _shell_deps(["bash"], mock_deps)
    result = await run_command(ctx, "bash -c 'exit 42'")
    assert "Exit code 42" in result


@pytest.mark.asyncio
async def test_run_command_strips_path(mock_deps):
    """Binary name matched by basename — /usr/bin/echo is the same as echo."""
    from kore.tools.shell import run_command
    ctx = _shell_deps(["echo"], mock_deps)
    result = await run_command(ctx, "/usr/bin/echo world")
    assert result == "world"
