"""Keywords for the 'Kargo / Lojistik' category.

Covers: shipping carriers, delivery status, lost/late packages, courier
behaviour. Cross-category-cleaned: "sevk edilmedi" lives only in
siparis_sureci; "paket bozuk/hasarlı" moved to urun_kalitesi.
"""

from __future__ import annotations

KARGO_KEYWORDS: frozenset[str] = frozenset({
    # Carrier / courier
    "kargo",
    "kargocu",
    "kargoluyor",
    "kuryem",
    "kurye",
    "kuryeci",
    "gönderim",
    "gönderdi",
    "gönderim yapılmadı",
    "kargocu gelmedi",
    # Delivery status
    "teslimat",
    "teslim alamadım",
    "teslim edilmedi",
    "teslim alındı",
    "ulaşmadı",
    "gelmedi",
    "geç geldi",
    "gecikti",
    "kayboldu",
    "kayıp",
    "kargoda kayboldu",
    "kargo bekliyorum",
    "paketim nerede",
    # Tracking
    "takip numarası",
    "takip kodu",
    # Carrier brand names
    "ptt",
    "yurtiçi",
    "mng",
    "aras",
    "sürat",
    "hepsijet",
    "trendyol express",
    # Distribution / hub-state
    "dağıtım",
    "dağıtıma çıkmadı",
    "şubeye düştü",
    "depoda bekliyor",
    "yola çıkmadı",
    # Address-side
    "yanlış adres",
    "adrese ulaşmadı",
})
