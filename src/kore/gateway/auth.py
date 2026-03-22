from __future__ import annotations

import secrets
from time import monotonic

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)
_WINDOW_SECONDS = 60.0


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> str:
    """FastAPI dependency — validates HTTP Basic credentials and enforces rate limit.

    Returns the authenticated username (or "anonymous" when auth is disabled).
    """
    cfg = request.app.state.config.security

    if not cfg.api_auth_enabled:
        return "anonymous"

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    expected_password = (
        cfg.api_password.get_secret_value() if cfg.api_password else ""
    )
    valid_user = secrets.compare_digest(
        credentials.username.encode(), cfg.api_username.encode()
    )
    valid_pass = secrets.compare_digest(
        credentials.password.encode(), expected_password.encode()
    )
    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    # Sliding-window rate limit.
    # There are no `await` points between the read and write below, so under
    # asyncio's cooperative-concurrency model this block is effectively atomic.
    # If an `await` is ever added here, replace with an asyncio.Lock per user.
    rate_buckets = request.app.state.rate_buckets
    now = monotonic()
    bucket = [t for t in rate_buckets[credentials.username] if now - t < _WINDOW_SECONDS]
    if len(bucket) >= cfg.rate_limit_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {cfg.rate_limit_per_user} requests per minute",
        )
    bucket.append(now)
    rate_buckets[credentials.username] = bucket

    return credentials.username
