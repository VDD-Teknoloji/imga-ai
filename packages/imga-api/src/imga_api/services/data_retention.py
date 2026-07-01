"""İmga v1 — KVKK 30-gün retention purge (contract §3.8/§9).

api_request_log satırları 30 günden eski olunca hard-delete edilir (KVKK saklama
sınırı). Ham gövde zaten hiç saklanmaz; bu job türetilmiş içeriği de
(response_summary + SHA-256 hash'ler) saklama penceresi dolunca temizler. Kanıt:
data_purge_audit (deny-all RLS → yalnız imga_admin/BYPASSRLS yazabilir).

Cross-tenant bakım → admin (BYPASSRLS) session bekler; tek bir tenant context'i
yok. Silme idempotent: eski satır kalmadıysa 0 döner.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from imga_db.models import ApiRequestLog, DataPurgeAudit
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("imga-api.data-retention")

RETENTION_DAYS = 30


async def purge_expired(
    session: AsyncSession, *, retention_days: int = RETENTION_DAYS
) -> int:
    """``retention_days`` günden eski api_request_log satırlarını sil + audit yaz.

    Admin (BYPASSRLS) session bekler (cross-tenant + data_purge_audit deny-all).
    Silinen satır sayısını döndürür."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with session.begin():
        result = await session.execute(
            delete(ApiRequestLog).where(ApiRequestLog.created_at < cutoff)
        )
        rows = result.rowcount or 0
        session.add(
            DataPurgeAudit(tenant_id=None, cutoff_date=cutoff, rows_purged=rows)
        )
    if rows:
        logger.info(
            "data retention: purged %s api_request_log rows < %s",
            rows,
            cutoff.isoformat(),
        )
    return rows


__all__ = ["purge_expired", "RETENTION_DAYS"]
