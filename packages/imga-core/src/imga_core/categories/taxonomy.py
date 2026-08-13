"""Global category taxonomy for business-unit routing.

Each complaint is classified into one of nine global categories. The taxonomy
is intentionally flat (no parent/child) to keep ticket routing simple. Tenants
can later extend or disable categories at the tenant-config level (Sprint 7).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class GlobalCategory(StrEnum):
    """Default global category taxonomy.

    Available to all tenants by default. Tenants may extend / disable at the
    tenant configuration level. The string values are the human-readable
    display names; `code` (in CategoryDefinition) is the stable identifier.
    """

    KARGO = "Kargo / Lojistik"
    FATURALAMA = "Faturalama / Ödeme"
    URUN_KALITESI = "Ürün Kalitesi"
    MUSTERI_HIZMETLERI = "Müşteri Hizmetleri"
    IADE = "İade / Değişim"
    TEKNIK_DESTEK = "Teknik Destek"
    SIPARIS_SURECI = "Sipariş Süreci"
    PAZARLAMA = "Pazarlama / İletişim"
    BELIRSIZ = "Belirsiz - Manuel İnceleme"


class CategoryDefinition(BaseModel):
    """A single category with its keywords and metadata.

    Used for both global default categories and tenant-specific ones.
    Keywords are matched case-insensitively as substrings against lowercased
    review text (same convention as the override lexicons).
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Display name shown in UI")
    code: str = Field(
        ...,
        description="Stable identifier for DB / API responses (lowercase, no spaces).",
    )
    keywords: frozenset[str] = Field(
        default_factory=frozenset,
        description="Substring patterns for keyword-based classification.",
    )
    is_fallback: bool = Field(
        default=False,
        description="True for the 'Belirsiz' bucket that catches unmatched reviews.",
    )


# Codes are stable identifiers used in the API and DB. Display names come from
# GlobalCategory.<X>.value. Keyword sets are populated in Stage 2 — left empty
# here so the scaffolding can land independently of the lexicon work.
DEFAULT_GLOBAL_CATEGORIES: Final[tuple[CategoryDefinition, ...]] = (
    CategoryDefinition(
        name=GlobalCategory.KARGO.value,
        code="kargo",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.FATURALAMA.value,
        code="faturalama",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.URUN_KALITESI.value,
        code="urun_kalitesi",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.MUSTERI_HIZMETLERI.value,
        code="musteri_hizmetleri",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.IADE.value,
        code="iade",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.TEKNIK_DESTEK.value,
        code="teknik_destek",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.SIPARIS_SURECI.value,
        code="siparis_sureci",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.PAZARLAMA.value,
        code="pazarlama",
        keywords=frozenset(),
    ),
    CategoryDefinition(
        name=GlobalCategory.BELIRSIZ.value,
        code="belirsiz",
        keywords=frozenset(),
        is_fallback=True,
    ),
)


# Convenience lookups used by the classifier and API layer.
GLOBAL_CATEGORY_BY_CODE: Final[dict[str, CategoryDefinition]] = {
    c.code: c for c in DEFAULT_GLOBAL_CATEGORIES
}

GLOBAL_CATEGORY_CODES: Final[tuple[str, ...]] = tuple(
    c.code for c in DEFAULT_GLOBAL_CATEGORIES
)

FALLBACK_CATEGORY_CODE: Final[str] = next(
    c.code for c in DEFAULT_GLOBAL_CATEGORIES if c.is_fallback
)


# 2026-08-10 hedef çalışması — sınıflandırıcı prompt'una giden kod
# TANIMLARI. Çıplak kod listesi %14,8 belirsiz + %76 kategori
# doğruluğu üretiyordu (gold4 taban çizgisi); tanım + sınır kuralları
# rehber (rubric v2) buradan beslenir. Kurum-özel kategoriler için
# DB'deki description alanı bu sözlüğü genişletir/ezer.
CATEGORY_DESCRIPTIONS_TR: Final[dict[str, str]] = {
    "kargo": (
        "Taşıma ve teslimatın kendisi: gecikme, kayıp, hareketsiz gönderi, "
        "yanlış/eksik teslimat, takip statüsü tutarsızlığı, gümrükte bekleme "
        "ve gümrük evrak süreci, taşıyıcı (FedEx/UPS vb.) süreçleri ve "
        "taşıyıcı bilgilendirme e-postaları, servis kapsamı soruları."
    ),
    "faturalama": (
        "Ücret ve para: fiyat farkı, fatura kesimi/düzeltmesi, vergi ve "
        "gümrük ÜCRETLERİ tartışması, iade edilen paranın gecikmesi, "
        "tahsilat. (Gümrükte bekleme kargo'dur; gümrük vergisi itirazı "
        "faturalamadır.)"
    ),
    "urun_kalitesi": (
        "Ürünün fiziksel durumu: hasarlı, kırık, eksik parça, yanlış ürün, "
        "ambalaj kaynaklı hasar."
    ),
    "musteri_hizmetleri": (
        "Destek deneyiminin KENDİSİ: cevapsızlık, geç dönüş, yanlış bilgi, "
        "ilgisizlik ya da destek ekibine övgü. Konu başka bir kategoriyse ve "
        "şikayet desteğin tutumuna değilse o kategori seçilir."
    ),
    "iade": (
        "İade/değişim SÜRECİ: iade talebi, onayı, geri gönderim, değişim, "
        "reklamasyon formları. (İade parasının gecikmesi faturalama; iade "
        "kargosunun kaybolması kargo.)"
    ),
    "teknik_destek": (
        "Yazılım/platform arızası: site veya uygulama hatası, giriş "
        "yapamama, takip kodunun sistemde çalışmaması, entegrasyon/API, "
        "buton/ekran hatası."
    ),
    "siparis_sureci": (
        "Sipariş oluşturma/işleme: sipariş verememe, yanlış kayıt, "
        "etiket/konşimento oluşturma, gönderi kaydı düzeltmeleri, evrak "
        "talepleri."
    ),
    "pazarlama": (
        "Kampanya, indirim, duyuru, tanıtım içeriği ve bunlarla ilgili "
        "soru/şikayet."
    ),
    "belirsiz": (
        "YALNIZCA anlamlı konu taşımayan metin (boşa yakın, bağlamsız, "
        "anlaşılamayan). Konusu olan mesaj belirsiz OLAMAZ; emin değilsen "
        "en yakın kategoriyi düşük cc ile seç."
    ),
}
