"""Tier-1 strong-negative-adjective override."""

from __future__ import annotations

from imga_core.config import TIER1_OVERRIDE_SCORE
from imga_core.lexicons import TIER1_SENTIMENT
from imga_core.models import OverrideHit


def apply_tier1_override(text: str) -> OverrideHit | None:
    """Return an OverrideHit if any Tier-1 adjective is present, else None."""
    if not text:
        return None
    lowered = text.lower()
    matched = sorted(kw for kw in TIER1_SENTIMENT if kw in lowered)
    if not matched:
        return None
    return OverrideHit(
        layer="tier1",
        matched_keywords=matched,
        score=TIER1_OVERRIDE_SCORE,
    )
