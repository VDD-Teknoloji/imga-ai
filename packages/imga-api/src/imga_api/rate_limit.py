"""Custom rate limiting via FastAPI ``Depends``.

Sprint 7.5.5 invitation endpoints (preview / accept / accept-existing)
are unauthenticated or thinly authenticated and accept a 256-bit token
in the URL path. Without rate limiting an attacker can mount a high-
volume guessing attack against the token surface even though the
math overwhelmingly favours us — guessing burns server budget for free.

We deliberately don't use slowapi's ``@limiter.limit`` decorator: it
runs ``functools.wraps`` over the route handler in a way that breaks
FastAPI's ``Annotated[X, Depends(...)]`` introspection (the wrapped
signature loses parameter annotations). Instead, ``RateLimitDep``
hangs off ``Depends(...)`` so the limiter check fires before the
route body but FastAPI's tip resolution stays untouched.

Two limit dimensions are applied per route via two stacked
``Depends(rate_limit_ip(...))`` + ``Depends(rate_limit_token(...))``:

  * IP — caps a single client at 10 requests / 60 seconds.
  * Token — caps requests per single token at 5 / 60 seconds.

Storage is in-memory keyed on ``(dimension, key, window_start)``.
Single-instance for dev / Sprint 8; a future Redis swap touches
this module only.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from threading import Lock

from fastapi import HTTPException, Request, status

# (dimension, key) -> [timestamps within the window]
_buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
_lock = Lock()


class RateLimitExceeded(HTTPException):
    """Raised when an IP / token exceeds its window. The 429 mapper
    in main.py prefers this dedicated subclass so the response shape
    stays stable."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": "60"},
        )


def _check(dimension: str, key: str, *, max_calls: int, window_seconds: float) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    bucket_key = (dimension, key)
    with _lock:
        timestamps = _buckets[bucket_key]
        # Drop expired hits.
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= max_calls:
            raise RateLimitExceeded(
                f"Çok fazla istek; lütfen sonra tekrar dene. ({max_calls}/{int(window_seconds)}s)"
            )
        timestamps.append(now)


def reset_for_tests() -> None:
    """Clear all buckets — call from a test fixture between cases."""
    with _lock:
        _buckets.clear()


def check_rate_limit(
    dimension: str, key: str, *, max_calls: int, window_seconds: float
) -> None:
    """Public manual check — for routes that need a key derived from the
    parsed body (e.g. login per-username) and so cannot use ``Depends``."""
    _check(dimension, key, max_calls=max_calls, window_seconds=window_seconds)


def _client_ip(request: Request) -> str:
    """X-Forwarded-For aware IP extraction. Trust the leftmost IP when
    the header is set; fall back to the socket peer otherwise. Sprint 8
    will tighten this with a trusted-proxy allow-list."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def rate_limit_ip(
    *,
    max_calls: int,
    window_seconds: float = 60.0,
    dimension: str = "ip",
) -> Callable[[Request], None]:
    """Per-IP limiter dependency factory.

    ``dimension`` namespaces the bucket so routes with different limits
    (e.g. /auth/login at 5/min vs /auth/refresh at 30/min) don't share
    state and trip each other. Default ``"ip"`` preserves Sprint 7.5.5
    invitation-route behaviour where preview/accept/accept-existing
    deliberately share a bucket."""

    def _dep(request: Request) -> None:
        _check(
            dimension,
            _client_ip(request),
            max_calls=max_calls,
            window_seconds=window_seconds,
        )

    return _dep


def rate_limit_token(*, max_calls: int, window_seconds: float = 60.0) -> Callable[[Request], None]:
    """Per-token limiter dependency factory. Reads the token from
    path_params; if missing the dimension key falls back to "unknown"
    so the limit still gates malformed requests."""

    def _dep(request: Request) -> None:
        token = request.path_params.get("token")
        key = token if isinstance(token, str) and token else "unknown"
        _check(
            "token",
            key,
            max_calls=max_calls,
            window_seconds=window_seconds,
        )

    return _dep


__all__ = [
    "RateLimitExceeded",
    "check_rate_limit",
    "rate_limit_ip",
    "rate_limit_token",
    "reset_for_tests",
]
