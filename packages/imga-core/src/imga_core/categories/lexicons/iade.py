"""Keywords for the 'İade / Değişim' category.

Cross-category-cleaned: this is the home of all refund/exchange phrases —
'iade tutarı', 'para iadesi', 'iade ödeme' previously in faturalama;
'iptal' / 'siparişimi iptal' belong here (the user wants the order undone),
while 'iptal edildi' (status, vendor-side) stays in siparis_sureci.
"""

from __future__ import annotations

IADE_KEYWORDS: frozenset[str] = frozenset({
    # Return verbs / phrasings
    "iade",
    "iade etmek",
    "iade istiyorum",
    "iade ediyorum",
    "geri iade",
    "geri gönderdim",
    "geri yolladım",
    "koli ile geri yolladım",
    # Return acceptance state
    "iade kabul",
    "iade kabul edilmedi",
    "iade reddedildi",
    "iade onaylanmadı",
    "iade alınmadı",
    # Return logistics / process
    "iade kargosu",
    "iade etiketi",
    "iade kodu",
    "iade adresi",
    "iade nereye",
    "iade prosedürü",
    "iade süresi",
    # Exchange
    "değişim",
    "değişim talebi",
    "değişim istiyorum",
    "değişim yapılmadı",
    "değişim reddedildi",
    "değişim koşulu",
    "değiştirmek istiyorum",
    # Cancel-as-refund (customer-initiated)
    "iptal",
    "iptal istiyorum",
    "siparişimi iptal",
    # Refund money (refund-tied money phrases live here, not in faturalama)
    "iade tutarı",
    "ücret iadesi",
    "para iadesi",
    "iade ödeme",
    "geri ödeme",
    # Cooling-off
    "cayma hakkı",
    "cayma süresi",
    "cayma süresi geçti",
})
