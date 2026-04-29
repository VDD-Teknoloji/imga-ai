"""Critical-keyword override (Tier-0): legal/security/safety incidents."""

from __future__ import annotations

from imga_core.config import CRITICAL_OVERRIDE_SCORE
from imga_core.lexicons import CRITICAL_KEYWORDS
from imga_core.models import OverrideHit
from imga_core.text_utils import normalize_turkish


def apply_critical_override(text: str) -> OverrideHit | None:
    """Return an OverrideHit if any critical keyword is present, else None."""
    if not text:
        return None
    lowered = normalize_turkish(text)
    matched = sorted(kw for kw in CRITICAL_KEYWORDS if kw in lowered)
    if not matched:
        return None
    return OverrideHit(
        layer="critical",
        matched_keywords=matched,
        score=CRITICAL_OVERRIDE_SCORE,
    )
