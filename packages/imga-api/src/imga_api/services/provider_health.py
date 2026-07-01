"""İmga v1 — provider (Gemini) sağlık durumu (contract §3.5/§4.7).

60 sn'de bir arka plan job'u Gemini'ye hafif bir liveness çağrısı atar
(``GeminiProvider.health_check`` → tek ``ping`` generation). Sonuç modül-düzeyi
state'te tutulur; ``GET /v1/health`` bunu okur. Tek-process (container başına) —
``tenant_config_cache`` ile aynı single-process kabulü.

Not: kod tabanında hazır liveness yolu ``health_check`` (generate_content) —
spec'in önerdiği ``models.list`` metadata çağrısı SDK sarmalayıcısında yok. 60 sn
interval'da minik bir generation maliyeti var; kabul edilebilir (günde ~1440 ping).
Body ASLA log'lanmaz — yalnız healthy bayrağı + zaman damgası.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger("imga-api.provider-health")

_MODEL_DEFAULT = "gemini-3-flash-preview"

# Tek-process paylaşılan durum. healthy=None → henüz hiç probe edilmedi.
_state: dict[str, object] = {"healthy": None, "last_checked_at": None}


def get_provider_health() -> tuple[bool | None, str | None]:
    """(healthy, last_checked_at_iso). healthy None → henüz probe koşmadı."""
    healthy = _state["healthy"]
    checked = _state["last_checked_at"]
    return (
        healthy if healthy is None else bool(healthy),
        checked if checked is None else str(checked),
    )


def _record(healthy: bool) -> None:
    _state["healthy"] = healthy
    _state["last_checked_at"] = datetime.now(UTC).isoformat()


async def probe_provider() -> None:
    """Gemini erişilebilirliğini yokla; state'i güncelle. ASLA exception fırlatmaz
    (scheduler job güvenliği). GEMINI_API_KEY yoksa unhealthy (yapılandırılmamış)."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        _record(False)
        return
    model = os.environ.get("IMGA_GEMINI_MODEL", _MODEL_DEFAULT)
    try:
        from imga_core.llm.gemini import GeminiProvider

        provider = GeminiProvider(
            api_key=api_key, model_name=model, timeout_seconds=10.0
        )
        # health_check senkron (SDK bloklar) → thread'e al, event loop'u bloklama.
        healthy = await asyncio.wait_for(
            asyncio.to_thread(provider.health_check), timeout=12.0
        )
        _record(bool(healthy))
    except Exception:  # noqa: BLE001 — probe hatası = unhealthy, job devam eder
        logger.warning("provider health probe failed", exc_info=True)
        _record(False)


__all__ = ["get_provider_health", "probe_provider"]
