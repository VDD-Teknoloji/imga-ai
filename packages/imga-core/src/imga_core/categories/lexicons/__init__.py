"""Per-category Turkish keyword lexicons.

Each lexicon is a `frozenset[str]` of lowercase substring patterns used by the
keyword classifier. Iteration order is non-deterministic for frozensets, so
any code that needs stable output must `sorted(...)` before consuming.
"""

from __future__ import annotations

from typing import Final

from imga_core.categories.lexicons.faturalama import FATURALAMA_KEYWORDS
from imga_core.categories.lexicons.iade import IADE_KEYWORDS
from imga_core.categories.lexicons.kargo import KARGO_KEYWORDS
from imga_core.categories.lexicons.musteri_hizmetleri import MUSTERI_HIZMETLERI_KEYWORDS
from imga_core.categories.lexicons.pazarlama import PAZARLAMA_KEYWORDS
from imga_core.categories.lexicons.siparis_sureci import SIPARIS_SURECI_KEYWORDS
from imga_core.categories.lexicons.teknik_destek import TEKNIK_DESTEK_KEYWORDS
from imga_core.categories.lexicons.urun_kalitesi import URUN_KALITESI_KEYWORDS

# Code -> keyword set. Codes match `CategoryDefinition.code` in taxonomy.py.
# 'belirsiz' has no keyword set — it's the fallback bucket selected when no
# other category matches above the confidence threshold.
ALL_CATEGORY_KEYWORDS: Final[dict[str, frozenset[str]]] = {
    "kargo": KARGO_KEYWORDS,
    "faturalama": FATURALAMA_KEYWORDS,
    "urun_kalitesi": URUN_KALITESI_KEYWORDS,
    "musteri_hizmetleri": MUSTERI_HIZMETLERI_KEYWORDS,
    "iade": IADE_KEYWORDS,
    "teknik_destek": TEKNIK_DESTEK_KEYWORDS,
    "siparis_sureci": SIPARIS_SURECI_KEYWORDS,
    "pazarlama": PAZARLAMA_KEYWORDS,
}

__all__ = [
    "ALL_CATEGORY_KEYWORDS",
    "FATURALAMA_KEYWORDS",
    "IADE_KEYWORDS",
    "KARGO_KEYWORDS",
    "MUSTERI_HIZMETLERI_KEYWORDS",
    "PAZARLAMA_KEYWORDS",
    "SIPARIS_SURECI_KEYWORDS",
    "TEKNIK_DESTEK_KEYWORDS",
    "URUN_KALITESI_KEYWORDS",
]
