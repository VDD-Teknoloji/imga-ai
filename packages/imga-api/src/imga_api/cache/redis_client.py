"""Process-level async Redis client.

Sprint 8.3.6 / Alt-Faz 8.3.6.3.D. Lazy singleton: the first
``get_redis_client()`` call lazy-binds an ``aioredis`` connection from
``REDIS_URL``; subsequent calls return the same instance. The client
uses asyncio so per-request handlers can ``await`` cache lookups
without a thread.

``set_redis_client`` is the test seam — fakeredis fixtures inject an
in-process double so unit tests don't need a real Redis container.
``close_redis_client`` runs from the FastAPI lifespan teardown so a
restart doesn't leak the asyncpg-style connection.

Caching is best-effort: callers should always tolerate a Redis-side
exception (timeout, connection refused) and fall through to the slow
path. The Sprint 8.3.6.3 SwotService wraps every cache op with a
try/except that logs the failure and continues; this module's job is
just to surface the client.
"""

from __future__ import annotations

import os
from typing import Any

import redis.asyncio as aioredis

# Module-level singleton. ``Any`` typing because ``aioredis.Redis`` is
# generic over the response decoder and we want to support both
# decode_responses=True (string) and False (bytes); the strong typing
# would force every call site to narrow.
_client: Any | None = None


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://redis:6379/0")


def get_redis_client() -> Any:
    """Return the process-singleton Redis client, lazy-initialising on
    first access. Sync because constructing ``aioredis.from_url``
    doesn't open a TCP connection — that happens on the first ``await``
    against the returned client.

    Returns:
        ``redis.asyncio.Redis`` (or whatever ``set_redis_client``
        injected — fakeredis instances satisfy the same interface).
    """
    global _client
    if _client is None:
        _client = aioredis.from_url(
            _redis_url(),
            decode_responses=False,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
    return _client


def set_redis_client(client: Any | None) -> None:
    """Test seam — replace the process-singleton with a fake. Pass
    ``None`` to reset (next ``get_redis_client`` lazy-binds a fresh
    real client). Production code never calls this."""
    global _client
    _client = client


async def close_redis_client() -> None:
    """Close the singleton if open. Idempotent. Called from the
    lifespan teardown in main.py so a graceful shutdown drains the
    Redis connection pool."""
    global _client
    if _client is not None:
        # ``aioredis.Redis.aclose`` (5.0+) is the documented async
        # close; ``close`` exists too but is sync on some versions.
        if hasattr(_client, "aclose"):
            await _client.aclose()
        elif hasattr(_client, "close"):
            maybe_coro = _client.close()
            if hasattr(maybe_coro, "__await__"):
                await maybe_coro
        _client = None
