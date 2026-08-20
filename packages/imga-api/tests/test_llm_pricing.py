"""``llm_pricing.cost_usd`` — statik fiyat tablosu birim testleri.

Saf fonksiyon, DB/Redis gerekmez — CI'nin ``api-test`` container'ında
koşar ama lokalde de doğrudan ``pytest tests/test_llm_pricing.py``
ile, Postgres/Redis olmadan çalışır (bkz. AGENTS.md test bölümü).
"""

from __future__ import annotations

from decimal import Decimal

from imga_api.services.llm_pricing import cost_usd


def test_known_model_computes_expected_cost() -> None:
    # z-ai/glm-5.2, openrouter: 1.19 / 3.74 USD per 1M token (görev
    # talimatındaki değer — bkz. llm_pricing.py docstring'indeki not).
    result = cost_usd("openrouter", "z-ai/glm-5.2", 1_000_000, 1_000_000)
    assert result == Decimal("1.19") + Decimal("3.74")


def test_known_model_partial_tokens() -> None:
    # 500k girdi + 250k çıktı -> (500_000/1e6)*1.19 + (250_000/1e6)*3.74
    result = cost_usd("openrouter", "z-ai/glm-5.2", 500_000, 250_000)
    expected = (Decimal(500_000) * Decimal("1.19") + Decimal(250_000) * Decimal("3.74")) / Decimal(
        1_000_000
    )
    assert result == expected.quantize(Decimal("0.000001"))


def test_unknown_model_returns_none() -> None:
    assert cost_usd("openrouter", "totally/unknown-model-xyz", 1000, 1000) is None


def test_unknown_provider_returns_none() -> None:
    assert cost_usd("anthropic", "z-ai/glm-5.2", 1000, 1000) is None


def test_both_token_counts_none_returns_none() -> None:
    """Başarısız / usage_metadata'sız çağrı — maliyet hesaplanamaz,
    0 SANILMAMALI."""
    assert cost_usd("openrouter", "z-ai/glm-5.2", None, None) is None


def test_one_token_count_none_treated_as_zero() -> None:
    """Yalnız biri None ise diğeri geçerli bir kısmi hesap üretir —
    ikisi birden None olan durumdan FARKLI davranış."""
    result = cost_usd("openrouter", "z-ai/glm-5.2", 1_000_000, None)
    assert result == Decimal("1.19")


def test_zero_tokens_is_a_known_zero_cost_not_none() -> None:
    """0/0 açıkça verilirse (None değil) bilinen bir fiyat tablosuna
    karşı hesap yapılabilir ve sonuç gerçekten sıfırdır."""
    result = cost_usd("openrouter", "z-ai/glm-5.2", 0, 0)
    assert result == Decimal("0")


def test_direct_gemini_provider_is_a_separate_key_from_openrouter() -> None:
    """provider="gemini" (doğrudan) ile provider="openrouter" aynı
    model adı için AYRI anahtarlardır — biri fiyatlanmış diğeri
    fiyatlanmamış olabilir."""
    direct = cost_usd("gemini", "gemini-2.5-flash", 1_000_000, 1_000_000)
    via_openrouter = cost_usd("openrouter", "google/gemini-2.5-flash", 1_000_000, 1_000_000)
    assert direct is not None
    assert via_openrouter is not None
    # Bu ikisi için (2.5 nesli) pass-through 1:1 olarak doğrulandı —
    # bkz. modül docstring'i.
    assert direct == via_openrouter


def test_unpriced_gemini_variant_returns_none() -> None:
    """3.6-flash yalnız openrouter anahtarında var; doğrudan "gemini"
    sağlayıcısı altında o model adı hiç eklenmedi (bkz. llm_pricing.py
    docstring'i) -> None, tahmin edilmemeli."""
    assert cost_usd("gemini", "gemini-3.6-flash", 1000, 1000) is None


def test_result_is_quantized_to_six_decimals() -> None:
    result = cost_usd("openrouter", "z-ai/glm-5.2", 1, 1)
    assert result is not None
    # Decimal.as_tuple().exponent -6 == altı ondalık basamağa
    # quantize edilmiş (NUMERIC(12,6) ile eşleşir).
    assert result.as_tuple().exponent == -6
