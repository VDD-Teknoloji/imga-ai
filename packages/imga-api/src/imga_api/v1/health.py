"""İmga v1 — Health (contract §4.7). Unauth liveness + provider durumu.

GET /v1/health → {status, version, region, providers:[{zone, healthy, last_checked_at}]}.
v1.3: region tüm istekler için "outbound" (residency düzleşti). Provider durumu
şimdilik statik "healthy"; canlı 60sn healthcheck job'u sonraki dilim (§3.5 TODO).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from imga_api.auth_deps import get_settings
from imga_api.settings import Settings

try:  # servis versiyonu — paket __version__'ı varsa
    from imga_api import __version__ as _SERVICE_VERSION
except Exception:  # pragma: no cover
    _SERVICE_VERSION = "0.0.0"

router = APIRouter(prefix="/v1", tags=["v1-health"])


class ProviderStatus(BaseModel):
    zone: Literal["tr", "outbound"]
    healthy: bool
    last_checked_at: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    region: Literal["tr", "outbound"]
    providers: list[ProviderStatus]


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    now = datetime.now(UTC).isoformat()
    # v1.3: tek bölge outbound (Gemini kanonik). Canlı provider probe'u
    # (Gemini models.list, 60sn job) sonraki dilim — şimdilik configured=healthy.
    provider_configured = settings.token_pepper is not None
    providers = [
        ProviderStatus(zone="outbound", healthy=True, last_checked_at=now)
    ]
    status_val: Literal["ok", "degraded", "down"] = (
        "ok" if provider_configured else "degraded"
    )
    return HealthResponse(
        status=status_val,
        version=_SERVICE_VERSION,
        region="outbound",
        providers=providers,
    )
