"""Tier-3 action-failure verbs/phrases.

Used by the heuristic summary generator (not by override layers). Verbatim from
legacy/app.py:235-238.
"""

from __future__ import annotations

TIER3_FAILURES: frozenset[str] = frozenset(
    {
        "gelmedi",
        "ulaşmadı",
        "yapılmadı",
        "etmedi",
        "açmadı",
        "kapattı",
        "dönmedi",
        "bitmedi",
        "ulaşamıyorum",
        "bağlanamıyorum",
        "cevap yok",
        "bekliyorum",
        "alamadım",
    }
)
