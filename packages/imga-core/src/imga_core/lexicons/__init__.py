"""Frozen Turkish keyword lexicons used by override and summary layers."""

from imga_core.lexicons.critical import CRITICAL_KEYWORDS
from imga_core.lexicons.tier1 import TIER1_SENTIMENT
from imga_core.lexicons.tier2 import TIER2_ISSUES
from imga_core.lexicons.tier3 import TIER3_FAILURES

__all__ = [
    "CRITICAL_KEYWORDS",
    "TIER1_SENTIMENT",
    "TIER2_ISSUES",
    "TIER3_FAILURES",
]
