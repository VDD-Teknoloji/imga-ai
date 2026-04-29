"""Keywords for the 'Ürün Kalitesi' category.

Covers: defects, damage, fakes, size mismatches, fabric/material problems,
spoilage, missing parts. 'paket bozuk/hasarlı' moved here from kargo because
the complaint is about the product condition, not the shipping itself.
"""

from __future__ import annotations

URUN_KALITESI_KEYWORDS: frozenset[str] = frozenset({
    # Defects / damage
    "defolu",
    "ayıplı",
    "hasarlı",
    "kusurlu",
    "bozuk",
    "bozuk geldi",
    "kırık",
    "kırık geldi",
    "yırtık",
    "leke",
    "lekeli",
    "yıpranmış",
    "kullanılmış gibi",
    "boya akmış",
    "pas",
    "çürük",
    "küflenmiş",
    # Authenticity
    "sahte",
    "replika",
    "orijinal değil",
    "taklit",
    # Quality
    "kalitesiz",
    "kötü kalite",
    "düşük kalite",
    "berbat kalite",
    # Sizing
    "beden büyük",
    "beden küçük",
    "beden uymadı",
    "yanlış beden",
    # Visual mismatch
    "renk farklı",
    "resimde farklı",
    "fotoğrafa benzemiyor",
    "tarif farklı",
    # Construction defects
    "dikiş bozuk",
    "dikiş atmış",
    "söküldü",
    "parçalandı",
    # Material
    "kumaş",
    "kumaş kalitesi",
    "malzeme",
    "malzeme zayıf",
    # Smell / spoilage
    "koku",
    "kötü koku",
    "bozulmuş",
    "son kullanma tarihi geçmiş",
    # Missing parts
    "eksik parça",
    "eksik geldi",
    "parça yok",
    "aksesuar yok",
    "kullanım kılavuzu yok",
})
