"""İmga v1 — Analyze endpoints (contract §2/§3/§4). tenant Bearer.

POST /v1/analyze/{use_case} — 6 use-case tek handler (§2 path param). Envelope
doğrula → Gemini engine → §3 zarfı + api_request_log (tenant RLS). Idempotency
(§3.7) + rate-limit header (§3.6) sonraki dilim; şu an cached=false.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status
from imga_db.models import ApiTenantConfig
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import get_settings
from imga_api.db_deps import get_app_session
from imga_api.services.api_request_log import record_request
from imga_api.services.partner_analyze import run_use_case
from imga_api.settings import Settings
from imga_api.v1 import idempotency, ratelimit
from imga_api.v1.auth import ApiPrincipal, bind_api_tenant, require_tenant
from imga_api.v1.envelope import (
    compute_cost_try,
    build_analyze_response,
    response_summary,
    sha256_hex,
)
from imga_api.v1.errors import PartnerApiError
from imga_api.v1.prompts import PROMPTS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/analyze", tags=["v1-analyze"])

# §6 varsayılan günlük token kotası — api_tenant_config satırı yoksa geçerli.
_QUOTA_DEFAULT = 2_000_000


class PartnerAnalyzeRequest(BaseModel):
    tenant_id: str
    use_case: str
    period: str
    period_start: str
    period_end: str
    context: dict
    user_prompt: str | None = None
    language: str = "tr"
    session_id: UUID | None = None
    client_request_id: UUID


def _invalid(message: str, field: str) -> PartnerApiError:
    return PartnerApiError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="invalid_input",
        message=message,
        details={"field": field},
    )


@router.post("/{use_case}")
async def analyze(
    body: PartnerAnalyzeRequest,
    request: Request,
    response: Response,
    principal: Annotated[ApiPrincipal, Depends(require_tenant)],
    settings: Annotated[Settings, Depends(get_settings)],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    use_case: Annotated[str, Path()],
) -> dict:
    # --- validation (§2/§4.6) ---
    if use_case not in PROMPTS:
        raise _invalid(f"unknown use_case: {use_case}", "use_case")
    if body.use_case != use_case:
        raise _invalid("body.use_case must match path", "use_case")
    if use_case == "free-analyze" and not (body.user_prompt or "").strip():
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_input",
            message="user_prompt required for free-analyze",
            details={"field": "user_prompt", "reason": "required_for_free_analyze"},
        )

    rid = getattr(request.state, "request_id", "") or ""
    tenant_key = str(principal.tenant_id)

    # §2.1 idempotency replay — aynı client_request_id → byte-identical
    cached = await idempotency.get_cached(tenant_key, str(body.client_request_id))
    if cached is not None:
        if isinstance(cached.get("meta"), dict):
            cached["meta"]["cached"] = True
        response.headers["Idempotency-Replayed"] = "true"
        response.headers["X-Imga-Request-Id"] = rid
        return cached

    # §6 rate-limit + per-tenant kota (§3.2 admin override; satır yoksa 2M).
    quota = await _tenant_quota(app_session, principal)
    await ratelimit.enforce(tenant_key, response, quota_tokens_per_day=quota)

    gemini_prompt = json.dumps(
        {
            "period": {
                "period": body.period,
                "from": body.period_start,
                "to": body.period_end,
            },
            "language": body.language,
            "context": body.context,
            "user_prompt": body.user_prompt,
        },
        ensure_ascii=False,
    )

    started = time.monotonic()
    try:
        payload, usage, real_model = await run_use_case(
            use_case=use_case, user_prompt=gemini_prompt
        )
    except PartnerApiError:
        # engine hataları zaten §5 kodlu — best-effort log + yeniden fırlat
        await _safe_log(
            app_session,
            principal,
            body,
            use_case,
            rid=rid,
            status_="error",
            context_hash=sha256_hex(gemini_prompt),
        )
        raise
    latency_ms = int((time.monotonic() - started) * 1000)

    cost = compute_cost_try(usage.total)
    envelope = build_analyze_response(
        request_id=rid,
        response_payload=payload,
        real_model=real_model,
        environment=settings.environment,
        usage=usage,
        latency_ms=latency_ms,
        cost_try=cost,
        cached=False,
        processed_in="outbound",
    )
    # request_id'yi zarftan al (rid boşsa engine sonrası da boş olabilir)
    envelope["request_id"] = rid
    response.headers["X-Imga-Request-Id"] = rid

    # §2.1 cache'e yaz + §6 günlük token sayacı
    await idempotency.store(tenant_key, str(body.client_request_id), envelope)
    await ratelimit.add_tokens(tenant_key, usage.total)

    resp_json = json.dumps(payload, ensure_ascii=False)
    await _safe_log(
        app_session,
        principal,
        body,
        use_case,
        rid=rid,
        status_="ok",
        context_hash=sha256_hex(gemini_prompt),
        response_hash=sha256_hex(resp_json),
        summary=response_summary(resp_json),
        usage_prompt=usage.prompt,
        usage_completion=usage.completion,
        cost=cost,
    )
    return envelope


async def _tenant_quota(
    app_session: AsyncSession, principal: ApiPrincipal
) -> int:
    """Per-tenant günlük token kotası (§3.2 admin override). api_tenant_config
    RLS+FORCE → tenant-bind'li kısa transaction ile kendi satırını okur; satır
    yoksa veya okuma hata verirse güvenli varsayılan (2M). Kota okuması ana
    isteği asla bozmaz."""
    if principal.tenant_id is None:
        return _QUOTA_DEFAULT
    try:
        async with app_session.begin():
            await bind_api_tenant(app_session, principal)
            quota = (
                await app_session.execute(
                    select(ApiTenantConfig.quota_tokens_per_day).where(
                        ApiTenantConfig.tenant_id == principal.tenant_id
                    )
                )
            ).scalar_one_or_none()
        return int(quota) if quota is not None else _QUOTA_DEFAULT
    except Exception:  # noqa: BLE001 — config okunamazsa güvenli varsayılan
        logger.warning("tenant quota read failed; using default", exc_info=True)
        return _QUOTA_DEFAULT


async def _safe_log(
    app_session: AsyncSession,
    principal: ApiPrincipal,
    body: PartnerAnalyzeRequest,
    use_case: str,
    *,
    rid: str,
    status_: str,
    context_hash: str | None = None,
    response_hash: str | None = None,
    summary: str | None = None,
    usage_prompt: int = 0,
    usage_completion: int = 0,
    cost=None,
) -> None:
    """Best-effort api_request_log — log hatası ana isteği bozmaz (goal §4)."""
    from decimal import Decimal

    from imga_api.v1.envelope import TokenUsage

    if principal.tenant_id is None:
        return
    try:
        async with app_session.begin():
            await bind_api_tenant(app_session, principal)
            await record_request(
                app_session,
                tenant_id=principal.tenant_id,
                request_id=rid or body.client_request_id.hex,
                use_case=use_case,
                status=status_,
                usage=TokenUsage(prompt=usage_prompt, completion=usage_completion),
                cost_try=cost if cost is not None else Decimal("0"),
                context_sha256=context_hash,
                response_sha256=response_hash,
                response_summary=summary,
                client_request_id=body.client_request_id,
                session_id=body.session_id,
            )
    except Exception:  # noqa: BLE001 — audit best-effort
        logger.warning("api_request_log write failed", exc_info=True)
