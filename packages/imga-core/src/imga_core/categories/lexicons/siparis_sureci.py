"""Keywords for the 'Sipariş Süreci' category.

Covers vendor-side order-lifecycle states from order placement through
preparation and dispatch. Cross-category-cleaned: 'sevk edilmedi' lives
here (not kargo); 'iptal edildi' (vendor cancels) lives here (not iade —
iade has 'iptal' / 'siparişimi iptal' for the customer-initiated flavour).
"""

from __future__ import annotations

SIPARIS_SURECI_KEYWORDS: frozenset[str] = frozenset({
    # Order references
    "sipariş",
    "siparişim",
    "siparişimi",
    "siparişimde",
    "sipariş numarası",
    "siparişim görünmüyor",
    "sipariş takibi",
    "sipariş veremedim",
    # Order acceptance
    "sipariş onaylanmadı",
    "sipariş alınmadı",
    "onay maili gelmedi",
    "onaylandı ama",
    # Preparation
    "hazırlanıyor",
    "hazırlanmadı",
    "hazırlanma süreci",
    "depoda bekliyor",
    "paketleme",
    "paketlenmedi",
    # Dispatch
    "sevk edilmedi",
    "kargoya verilmedi",
    # Wrong / missing items in shipment
    "yanlış ürün",
    "yanlış gönderim",
    "eksik ürün",
    "eksik gönderim",
    # Stock / supply
    "stokta yok",
    "stok hatası",
    "temin edilemedi",
    "tedarik",
    "tedarik süresi uzun",
    "ön sipariş",
    "bekleyen sipariş",
    "bekleme süresi",
    # Vendor-side cancel
    "iptal edildi",
})
