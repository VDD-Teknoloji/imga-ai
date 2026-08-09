"""Kazanan kimlik seçiminden yapılandırılmış-üretim sağlayıcısı kur.

SWOT / OKR / brifing servisleri kurum-başına sağlayıcı + model
seçimini ``load_active_llm_keys``'ten alır ve buradaki fabrikayla
sağlayıcı örneğini kurar. ``api_key="x"`` bilinçli: gerçek anahtar her
çağrıda rotator'dan geçer (çok-anahtarlı rotasyon deseni), kurucudaki
anahtar hiç kullanılmaz.
"""

from __future__ import annotations

from imga_core.llm import DEFAULT_OPENROUTER_MODEL, OpenRouterProvider
from imga_core.llm.gemini import GeminiProvider

StructuredProvider = GeminiProvider | OpenRouterProvider

# Üç stratejik servisin ortak Gemini varsayılanı — tarihçe için
# executive_briefing_service.DEFAULT_MODEL_NAME yorumuna bak.
GEMINI_STRUCTURED_DEFAULT_MODEL = "gemini-3-flash-preview"


def build_structured_provider(provider: str) -> StructuredProvider:
    if provider == "openrouter":
        return OpenRouterProvider(api_key="x")
    return GeminiProvider(api_key="x", model_name=GEMINI_STRUCTURED_DEFAULT_MODEL)


def resolve_model_name(provider: str, model: str | None) -> str:
    """Kimlik kaydındaki model NULL ise sağlayıcı varsayılanına düş."""
    if model:
        return model
    if provider == "openrouter":
        return DEFAULT_OPENROUTER_MODEL
    return GEMINI_STRUCTURED_DEFAULT_MODEL
