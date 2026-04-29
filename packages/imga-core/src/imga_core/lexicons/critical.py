"""Tier-0 critical keywords: legal, security, safety incidents.

Triggers the strongest negative override. Verbatim from legacy/app.py:212-215.
"""

from __future__ import annotations

CRITICAL_KEYWORDS: frozenset[str] = frozenset(
    {
        "hırsızlık",
        "hırsız",
        "suçlama",
        "alarm",
        "polis",
        "mahkeme",
        "dava",
        "savcılık",
        "tehdit",
        "taciz",
        "hakaret",
        "küfür",
        "güvenlik",
        "etiket",
        "unutulmuş",
    }
)
