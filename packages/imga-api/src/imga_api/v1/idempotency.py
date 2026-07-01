"""İmga v1 idempotency (contract §2.1). Redis 24h replay cache.

(tenant_id, client_request_id) → başarılı response envelope, 24 saat. Replay
hit'te byte-identical döner, meta.cached=true, Idempotency-Replayed header,
LLM tekrar çağrılmaz, kota azalmaz. Yalnız ok:true yanıtlar cache'lenir.
Redis down → cache miss (fresh execution).
"""

from __future__ import annotations

import json
from typing import Any

from imga_api.cache.redis_client import get_redis_client

_TTL_SECONDS = 24 * 3600


def _key(tenant_key: str, client_request_id: str) -> str:
    return f"imgav1:idem:{tenant_key}:{client_request_id}"


async def get_cached(
    tenant_key: str, client_request_id: str
) -> dict[str, Any] | None:
    client = get_redis_client()
    try:
        raw = await client.get(_key(tenant_key, client_request_id))
    except Exception:  # noqa: BLE001 — Redis down → miss
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


async def store(
    tenant_key: str, client_request_id: str, envelope: dict[str, Any]
) -> None:
    client = get_redis_client()
    try:
        await client.set(
            _key(tenant_key, client_request_id),
            json.dumps(envelope, ensure_ascii=False),
            ex=_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return


__all__ = ["get_cached", "store"]
