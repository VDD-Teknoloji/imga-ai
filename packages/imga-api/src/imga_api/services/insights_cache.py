"""Best-effort Redis cache helpers for the Sprint 8.3.9 insight services.

CohortAnalyzer / WordCloudGenerator / HeatmapGenerator each compute
heavy aggregations the user-facing dashboard re-fires on every URL-
state change. The wrapper falls through on Redis errors so the
analytic path always works (slow-path cost), and serialises payloads
as UTF-8 JSON with ``ensure_ascii=False`` so Türkçe characters stay
human-readable in cache dumps.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from imga_api.cache.redis_client import get_redis_client

_logger = logging.getLogger(__name__)


async def cache_get_or_compute(
    key: str,
    *,
    ttl_seconds: int,
    compute: Callable[[], Awaitable[dict[str, Any]]],
    label: str,
) -> dict[str, Any]:
    """Try Redis ``GET key`` first; on miss / Redis error, await
    ``compute()`` and write the result back. ``label`` shows up in
    the warning log so a Redis blip is identifiable in stdout."""
    try:
        client = get_redis_client()
        raw = await client.get(key)
    except Exception as exc:
        _logger.warning(
            "%s cache get failed (%s); falling through to compute",
            label, exc,
        )
        raw = None

    if raw is not None:
        try:
            data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError) as exc:
            _logger.warning(
                "%s cache holds malformed payload at %s (%s); "
                "treating as miss",
                label, key, exc,
            )

    payload = await compute()

    try:
        client = get_redis_client()
        await client.set(
            key,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ex=ttl_seconds,
        )
    except Exception as exc:
        _logger.warning(
            "%s cache set failed (%s); continuing without cache",
            label, exc,
        )

    return payload


__all__ = ["cache_get_or_compute"]
