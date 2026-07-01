"""İmga v1 — Health (contract §4.7). Unauth liveness + provider durumu.

GET /v1/health → {status, version, region, providers:[{zone, healthy, last_checked_at}]}.
v1.3: region tüm istekler için "outbound" (residency düzleşti). Provider durumu
canlı: 60sn'de bir arka plan job'u (§3.5) Gemini'yi yoklar, sonucu buradan okuruz.
İlk probe boot'ta hemen tetiklenir; o anki ~saniyelik pencerede henüz sonuç yoksa
GEMINI_API_KEY varlığına göre iyimser fallback.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from imga_api.auth_deps import get_settings
from imga_api.services.provider_health import get_provider_health
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
    # v1.3: tek bölge outbound (Gemini kanonik). Canlı durum §3.5 probe job'undan.
    healthy, last_checked = get_provider_health()
    if healthy is None:
        # Henüz probe koşmadı (boot penceresi) → GEMINI_API_KEY varsa iyimser.
        healthy = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        last_checked = now
    providers = [
        ProviderStatus(
            zone="outbound",
            healthy=healthy,
            last_checked_at=last_checked or now,
        )
    ]
    status_val: Literal["ok", "degraded", "down"] = "ok" if healthy else "degraded"
    return HealthResponse(
        status=status_val,
        version=_SERVICE_VERSION,
        region="outbound",
        providers=providers,
    )
