"""Company-perspective heuristic — keyword-driven 21-cat classifier.

Sprint 8.3.5 / Alt-Faz 8.3.5.5. Pure function, no DB. The caller (the
API service layer) loads the per-tenant taxonomy from
``category_taxonomies`` and passes the rows in as ``taxonomy``; we
return the best-matching taxonomy entry as a ``CompanyHeuristicHit``
or ``None`` if nothing matched.

This is the "Şirket Perspektifi" dimension from the legacy
cx_sentiment_dashboard's get_company_perspective. It complements
(does not replace) the BERT primary category — the dashboard shows
both as separate columns. BERT keeps classifying into the 8 broad
codes (kargo, iade, fatura, ...); this heuristic adds the 21 fine
company-perspective codes (shipment_not_arrived, broken_damaged, ...).

Confidence model:
  * Single keyword match → ``base_confidence * keyword_boost`` (0.5 * 1.2 = 0.6).
  * Each additional keyword multiplies again (0.5 * 1.44 = 0.72), capped at 1.0.
  * Ties on confidence resolve by taxonomy ``priority`` (lower wins) —
    that mirrors the legacy if-elif order so a rebuilt taxonomy keeps
    the original "kargom ulaşmadı" → "deforme" → ... resolution.

Empty taxonomy → None. No keyword match → None. The caller decides
whether to fall back to a hardcoded classifier or leave the company
perspective empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from imga_core.text_utils import normalize_turkish

# Calibration knobs. Defaults pinned to "BERT %50 baseline + 1.2x per
# keyword" the spec calls out: a single-keyword match jumps the
# heuristic confidence from 0.5 to 0.6, multiple matches keep
# multiplying until the cap. Callers can override via kwargs if a
# different sensitivity is needed.
_DEFAULT_BASE_CONFIDENCE = 0.5
_DEFAULT_KEYWORD_BOOST = 1.2
_MAX_CONFIDENCE = 1.0


class TaxonomyEntry(TypedDict):
    """Wire shape mirroring a row of ``category_taxonomies``. The API
    service layer adapts SQLAlchemy ORM rows into this dict before
    handing them to ``apply_company_heuristic`` — keeps imga-core
    headless (no SQLAlchemy / DB session import here)."""

    code: str
    label_tr: str
    keywords: list[str]
    priority: int


@dataclass(frozen=True, slots=True)
class CompanyHeuristicHit:
    """One taxonomy entry's heuristic match against a review's text."""

    code: str
    label_tr: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)


def apply_company_heuristic(
    review_text: str,
    taxonomy: list[TaxonomyEntry],
    *,
    base_confidence: float = _DEFAULT_BASE_CONFIDENCE,
    keyword_boost: float = _DEFAULT_KEYWORD_BOOST,
) -> CompanyHeuristicHit | None:
    """Pick the best-matching taxonomy entry, or None.

    Each taxonomy entry's keywords are tested against the
    ``normalize_turkish``-folded review text. An entry contributes
    ``len(matched_keywords)`` boost multiplications to its base
    confidence; the highest-confidence entry wins, with priority
    breaking ties (lower priority number = higher precedence).

    Safe defaults — empty taxonomy or zero keyword hits return None
    rather than a fake low-confidence match. The caller decides
    whether to fall back.
    """
    if not taxonomy or not review_text:
        return None

    folded = normalize_turkish(review_text)

    best: CompanyHeuristicHit | None = None
    best_priority: int | None = None
    for entry in taxonomy:
        keywords = entry["keywords"]
        if not keywords:
            continue
        matched = [kw for kw in keywords if kw in folded]
        if not matched:
            continue
        confidence = min(
            base_confidence * (keyword_boost ** len(matched)),
            _MAX_CONFIDENCE,
        )
        # Higher confidence wins; on tie, lower priority wins.
        if (
            best is None
            or confidence > best.confidence
            or (
                confidence == best.confidence
                and best_priority is not None
                and entry["priority"] < best_priority
            )
        ):
            best = CompanyHeuristicHit(
                code=entry["code"],
                label_tr=entry["label_tr"],
                confidence=round(confidence, 3),
                matched_keywords=matched,
            )
            best_priority = entry["priority"]

    return best
