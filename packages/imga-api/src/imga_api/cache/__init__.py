"""Sprint 8.3.6 — process-level Redis client + cache helpers.

The SWOT generator's 24h cache and (Sprint 8.3.6.5) the Gemini key
rotator's failure state both live in this Redis. Other long-lived
caches (per-tenant config TTLCache) stay in-process for now.
"""

from imga_api.cache.redis_client import (
    close_redis_client,
    get_redis_client,
    set_redis_client,
)

__all__ = [
    "close_redis_client",
    "get_redis_client",
    "set_redis_client",
]
