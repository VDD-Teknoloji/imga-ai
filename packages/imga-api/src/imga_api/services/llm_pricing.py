"""B6 — LLM çağrısı başına tahmini USD maliyeti.

Statik fiyat tablosu, ``(provider, model_name)`` anahtarlı. ``provider``
"gemini" (doğrudan Google API — ``imga_core.llm.gemini`` / ``rotating_gemini``)
ile "openrouter" (proxy) AYRI anahtarlardır: aynı model iki sağlayıcıda
farklı fiyata tabi olabilir — 2026-08-20 itibariyle OpenRouter'ın canlı
katalogunu (``https://openrouter.ai/api/v1/models``) doğrudan sorgulayarak
doğrulandı, ör. ``google/gemini-3.5-flash-lite`` OpenRouter üzerinden
Google'ın kendi yayınladığı doğrudan-API fiyatının (bilinen: 0.15/1.25)
TAM İKİ KATI (0.30/2.50) — pass-through her zaman 1:1 değil.

fiyatlar elle güncellenir; None = maliyet bilinmiyor. Bilinmeyen
(provider, model_name) çifti VEYA hiç token sayısı taşımayan bir çağrı
(başarısız/usage_metadata'sız) için ``cost_usd()`` None döner — okuma
tarafı (özet endpoint'leri) bunu 0 ile KARIŞTIRMAMALI, ayrı sayılmalı
(``unknown_cost_calls``).

Kaynaklar (2026-08-20):
  * z-ai/glm-5.2 — 1.19 / 3.74, OpenRouter canlı katalogundan
    (2026-08-18 sorgusu). 0.966 / 3.036 değeri z-ai/glm-5.1'in satırı —
    katalog okurken karıştırma.
  * google/gemini-* (openrouter) — OpenRouter'ın canlı model katalogu
    doğrudan sorgulanarak (``pricing.prompt`` / ``pricing.completion``,
    USD/token, ×1e6 ile USD/1M'ye çevrildi) doğrulandı.
  * gemini-2.5-pro / gemini-2.5-flash (doğrudan "gemini" sağlayıcısı) —
    OpenRouter'ın aynı model için gösterdiği fiyatla BİREBİR aynı
    (Google'ın kendi yayınladığı liste fiyatıyla örtüşüyor); bu ikisi
    için pass-through 1:1 kabul edildi.
  * gemini-3-flash-preview (doğrudan "gemini" sağlayıcısı, bkz.
    ``executive_briefing_service.DEFAULT_MODEL_NAME`` — platformun şu
    anki fiili varsayılanı) — doğrudan Google fiyatı BAĞIMSIZ
    DOĞRULANMADI; OpenRouter'ın gösterdiği 0.50/3.00 en iyi tahmin
    olarak kullanıldı. Doğrudan fiyat netleşince burası güncellenmeli.
"""

from __future__ import annotations

from decimal import Decimal

# (provider, model_name) -> (USD / 1M girdi token, USD / 1M çıktı token)
_PRICES_PER_MILLION_USD: dict[str, dict[str, tuple[Decimal, Decimal]]] = {
    "openrouter": {
        # 2026-08-10 Navlungo benchmark birincisi, sistem varsayılanı
        # (bkz. llm_credential_crud.py CURATED_OPENROUTER_MODELS).
        # Değer görev talimatından — modül docstring'indeki not'a bkz.
        "z-ai/glm-5.2": (Decimal("1.19"), Decimal("3.74")),
        "google/gemini-2.5-pro": (Decimal("1.25"), Decimal("10.00")),
        "google/gemini-2.5-flash": (Decimal("0.30"), Decimal("2.50")),
        "google/gemini-3.6-flash": (Decimal("0.75"), Decimal("3.75")),
        "google/gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50")),
        "google/gemini-3-flash-preview": (Decimal("0.50"), Decimal("3.00")),
    },
    "gemini": {
        # Doğrudan Google API — bkz. modül docstring'indeki kaynak notu.
        "gemini-2.5-pro": (Decimal("1.25"), Decimal("10.00")),
        "gemini-2.5-flash": (Decimal("0.30"), Decimal("2.50")),
        "gemini-3-flash-preview": (Decimal("0.50"), Decimal("3.00")),
    },
}

_QUANTUM = Decimal("0.000001")  # NUMERIC(12,6) ile eşleşir


def cost_usd(
    provider: str,
    model_name: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> Decimal | None:
    """Bir LLM çağrısının tahmini USD maliyeti.

    ``provider`` + ``model_name`` statik tabloda yoksa (ör. yeni bir
    OpenRouter modeli fiyat tablosuna henüz elle eklenmedi) None döner
    — 0 DEĞİL, "bilinmiyor" anlamına gelir. ``input_tokens`` ve
    ``output_tokens`` ikisi de None ise (başarısız çağrı / SDK
    usage_metadata döndürmedi) de None döner: token sayısı yoksa
    maliyet hesaplanamaz, sıfır sanılmamalı. Yalnız biri None ise
    diğeri 0 kabul edilir (kısmi ama geçerli bir hesap)."""
    prices = _PRICES_PER_MILLION_USD.get(provider, {}).get(model_name)
    if prices is None:
        return None
    if input_tokens is None and output_tokens is None:
        return None
    input_price, output_price = prices
    in_tok = Decimal(input_tokens or 0)
    out_tok = Decimal(output_tokens or 0)
    total = (in_tok * input_price + out_tok * output_price) / Decimal(1_000_000)
    return total.quantize(_QUANTUM)


__all__ = ["cost_usd"]
