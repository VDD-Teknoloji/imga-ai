"""api_request_log kaydı — İmga v1 usage/billing/KVKK (contract §4A.2/§6/§4.9).

Her v1 analyze isteği bir satır yazar (başarılı + hatalı). Ham prompt/response
gövdesi SAKLANMAZ — yalnız SHA-256 hash + 200-char özet + token/cost metadata
(KVKK veri-minimizasyonu; goal §4). §4.8 silme session_id ile, §4.9 export
buradan okur.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from imga_db.models import ApiRequestLog

from imga_api.v1.envelope import TokenUsage


async def record_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: str,
    use_case: str,
    status: str,
    processed_in: str = "outbound",
    usage: TokenUsage | None = None,
    cost_try: Decimal = Decimal("0"),
    context_sha256: str | None = None,
    response_sha256: str | None = None,
    response_summary: str | None = None,
    client_request_id: UUID | None = None,
    session_id: UUID | None = None,
) -> None:
    """Tek satır ekle. Çağıran kendi transaction'ında (RLS bağlı) çalıştırır;
    audit best-effort — kayıt hatası ana isteği bozmamalı (çağıran try/except)."""
    u = usage or TokenUsage(prompt=0, completion=0)
    session.add(
        ApiRequestLog(
            tenant_id=tenant_id,
            request_id=request_id,
            client_request_id=client_request_id,
            session_id=session_id,
            use_case=use_case,
            processed_in=processed_in,
            tokens_prompt=u.prompt,
            tokens_completion=u.completion,
            tokens_total=u.total,
            cost_try=cost_try,
            status=status,
            context_sha256=context_sha256,
            response_sha256=response_sha256,
            response_summary=response_summary,
        )
    )


__all__ = ["record_request"]
