"""Tier-2 operational-keyword fallback (post-BERT)."""

from __future__ import annotations

from imga_core.config import TIER2_FALLBACK_SCORE, TIER2_FALLBACK_TRIGGER_THRESHOLD
from imga_core.lexicons import TIER2_ISSUES
from imga_core.models import OverrideHit


def apply_tier2_fallback(text: str, current_score: float) -> OverrideHit | None:
    """Fire only when BERT did not classify the text as negative enough.

    Args:
        text: Original review text.
        current_score: Score assigned by BERT (or any prior layer).

    Returns:
        OverrideHit when an operational keyword is present and the current
        score is above the negative threshold; None otherwise.
    """
    if not text:
        return None
    if current_score <= TIER2_FALLBACK_TRIGGER_THRESHOLD:
        return None

    lowered = text.lower()
    matched = sorted(kw for kw in TIER2_ISSUES if kw in lowered)
    if not matched:
        return None
    return OverrideHit(
        layer="tier2",
        matched_keywords=matched,
        score=TIER2_FALLBACK_SCORE,
    )
