"""Tier-2 operational pain-point keywords.

Used as a post-BERT fallback when the model failed to detect negativity but
operational issues are clearly mentioned. Verbatim from legacy/app.py:227-232.
"""

from __future__ import annotations

TIER2_ISSUES: frozenset[str] = frozenset(
    {
        "iade",
        "iptal",
        "ücret",
        "para",
        "teslimat",
        "kargo",
        "gecikme",
        "bozuk",
        "defolu",
        "eksik",
        "yanlış",
        "sahte",
        "hile",
        "yalan",
        "tutar",
        "fatura",
        "kayıp",
        "hasarlı",
        "beden",
        "kalite",
        "kumaş",
        "dikiş",
        "leke",
        "ayıplı",
        "kusurlu",
        "değişim",
        "reddedildi",
        "kabul edilmedi",
        "red",
        "kırık",
    }
)
