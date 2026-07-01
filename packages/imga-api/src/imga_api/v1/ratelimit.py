"""İmga v1 rate-limit + kota (contract §6). Redis sliding window.

Per-tenant: 60 req/dk + 600 req/saat + günlük token kotası. Header'lar her
yanıtta (§3.5 matrisi). Redis down → fail-open (rate-limit güvenlik değil, log
ile geç; contract test Redis açıkken koşar). Kota reset 00:00 Europe/Istanbul.
"""

from __future__ import annotations

import time

from fastapi import Response

from imga_api.cache.redis_client import get_redis_client
from imga_api.v1.errors import PartnerApiError

MINUTE_LIMIT = 60
HOUR_LIMIT = 600
_IST_OFFSET = 3 * 3600  # Europe/Istanbul UTC+3 (DST yok)


def _headers(
    remaining: int, reset: int, quota_remaining: int, quota_reset: int
) -> dict[str, str]:
    return {
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
        "X-Quota-Tokens-Remaining": str(quota_remaining),
        "X-Quota-Reset": str(quota_reset),
    }


async def enforce(
    tenant_key: str, response: Response, *, quota_tokens_per_day: int
) -> None:
    """Dakika/saat limitini + günlük token kotasını uygula; header'ları set et.
    Aşımda 429 (rate_limit / quota_exceeded), header'lar 429'da da yanıtta."""
    client = get_redis_client()
    now = int(time.time())
    minute = now // 60
    hour = now // 3600
    day = (now + _IST_OFFSET) // 86400
    reset_minute = (minute + 1) * 60
    quota_reset = (day + 1) * 86400 - _IST_OFFSET
    try:
        m_key = f"imgav1:rl:m:{tenant_key}:{minute}"
        h_key = f"imgav1:rl:h:{tenant_key}:{hour}"
        q_key = f"imgav1:q:{tenant_key}:{day}"
        m = int(await client.incr(m_key))
        await client.expire(m_key, 120)
        h = int(await client.incr(h_key))
        await client.expire(h_key, 7200)
        used = int(await client.get(q_key) or 0)
    except Exception:  # noqa: BLE001 — Redis down → fail-open
        return
    headers = _headers(
        max(0, MINUTE_LIMIT - m),
        reset_minute,
        max(0, quota_tokens_per_day - used),
        quota_reset,
    )
    for k, v in headers.items():
        response.headers[k] = v
    if used >= quota_tokens_per_day:
        raise PartnerApiError(
            status_code=429,
            code="quota_exceeded",
            message="daily token quota exhausted",
            retry_after_seconds=max(1, quota_reset - now),
            extra_headers=headers,
        )
    if m > MINUTE_LIMIT or h > HOUR_LIMIT:
        raise PartnerApiError(
            status_code=429,
            code="rate_limit",
            message="rate limit exceeded",
            retry_after_seconds=max(1, reset_minute - now),
            extra_headers=headers,
        )


async def add_tokens(tenant_key: str, tokens: int) -> None:
    """Başarılı çağrının token'ını günlük kotaya ekle (idempotency replay hariç)."""
    if tokens <= 0:
        return
    client = get_redis_client()
    now = int(time.time())
    day = (now + _IST_OFFSET) // 86400
    q_key = f"imgav1:q:{tenant_key}:{day}"
    try:
        await client.incrby(q_key, tokens)
        await client.expire(q_key, 90_000)  # ~25 saat
    except Exception:  # noqa: BLE001
        return


__all__ = ["enforce", "add_tokens", "MINUTE_LIMIT", "HOUR_LIMIT"]
