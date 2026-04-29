"""Tier-1 strong-negative sentiment adjectives.

Triggers a hard negative override before BERT inference. Verbatim from
legacy/app.py:220-224.
"""

from __future__ import annotations

TIER1_SENTIMENT: frozenset[str] = frozenset(
    {
        "ilgisiz",
        "saygısız",
        "kaba",
        "çözümsüz",
        "mağdur",
        "rezalet",
        "berbat",
        "iğrenç",
        "profesyonellikten uzak",
        "lakayıt",
        "bilgisiz",
        "yetersiz",
        "sorumsuz",
        "dalga geçer gibi",
        "oyalayıcı",
        "ezbere",
        "küstah",
        "yalancı",
        "fiyasko",
        "alaya",
        "aptal",
        "dalga",
    }
)
