"""SLA-based override: detect duration mentions and compare to operational limits."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from imga_core.config import (
    DEFAULT_MAX_SHIPPING_DAYS,
    DEFAULT_MAX_WAREHOUSE_DAYS,
    SLA_BREACH_SCORE,
    SLA_COMPLIANT_SCORE,
    SLA_SHIPPING_CONTEXT_KEYWORDS,
    SLA_WAREHOUSE_CONTEXT_KEYWORDS,
)
from imga_core.models import OverrideHit
from imga_core.text_utils import normalize_turkish

# Verbatim from legacy/app.py:410.
DURATION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(\d+)\s*(?:gün|iş günü|hafta)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SLAParams:
    """Per-context SLA day limits, injected by the caller."""

    max_shipping_days: int = DEFAULT_MAX_SHIPPING_DAYS
    max_warehouse_days: int = DEFAULT_MAX_WAREHOUSE_DAYS


def apply_sla_override(text: str, params: SLAParams | None = None) -> OverrideHit | None:
    """Detect a duration mention and emit an SLA compliance/breach override.

    Returns None if no duration is detected, or if no shipping/warehouse
    context keyword accompanies it.
    """
    if not text:
        return None
    params = params or SLAParams()

    lowered = normalize_turkish(text)
    match = DURATION_PATTERN.search(lowered)
    if match is None:
        return None

    days = int(match.group(1))
    if "hafta" in match.group(0):
        days *= 7

    sla_limit, context = _resolve_context(lowered, params)
    if sla_limit is None or context is None:
        return None

    if days <= sla_limit:
        score = SLA_COMPLIANT_SCORE
        detail = f"SLA Uyumlu ({days} Gün <= {sla_limit})"
    else:
        score = SLA_BREACH_SCORE
        detail = f"SLA Aşımı ({days} Gün > {sla_limit})"

    return OverrideHit(
        layer="sla",
        matched_keywords=[match.group(0)],
        score=score,
        detail=detail,
    )


def _resolve_context(lowered: str, params: SLAParams) -> tuple[int | None, str | None]:
    """Pick the SLA limit based on which context keywords are present."""
    if any(kw in lowered for kw in SLA_SHIPPING_CONTEXT_KEYWORDS):
        return params.max_shipping_days, "shipping"
    if any(kw in lowered for kw in SLA_WAREHOUSE_CONTEXT_KEYWORDS):
        return params.max_warehouse_days, "warehouse"
    return None, None
