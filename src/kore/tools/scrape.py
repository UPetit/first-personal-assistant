from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from pydantic_ai import RunContext

from kore.agents.deps import KoreDeps
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

    if not addr_infos:
        return "[Error: DNS resolution failed — no addresses found]"

    for addr_info in addr_infos:
        ip_str = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return "[Error: Blocked — unrecognized IP address format]"
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            return "[Error: Blocked — private/internal URL]"

    return None


async def scrape_url(ctx: RunContext[KoreDeps], url: str) -> str:
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
