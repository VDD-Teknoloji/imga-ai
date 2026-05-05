"""Shared types for the smart_parser package.

Sprint 8.3.8. ``FieldName`` enumerates the logical fields the
detectors can recognise; ``DetectorResult`` is what one detector
emits per column when it matches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FieldName(StrEnum):
    """Logical field types the orchestrator can assign to a column."""

    REVIEW_TEXT = "review_text"
    NPS_SCORE = "nps_score"
    DATE = "date"
    CUSTOMER_ID = "customer_id"
    # Sprint 8.3.8 additions.
    ORDER_ID = "order_id"
    PRODUCT_NAME = "product_name"
    CUSTOMER_NAME = "customer_name"
    PRICE = "price"
    # Frontend-only sentinels — not emitted by detectors but used in
    # the UI dropdown so a user can mark a column as "ignore".
    IGNORE = "ignore"


# Confidence thresholds the UI maps to colour bands. Kept in this
# module so both the detectors and the frontend reuse the same cut-
# offs (frontend re-declares as constants in types.ts; the values
# match here).
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.55
CONFIDENCE_LOW = 0.30


@dataclass(frozen=True)
class DetectorResult:
    """One detector's verdict for one column.

    Attributes:
        field_name: which logical field this detector recognises.
        column_name: the original header string (preserved verbatim
            so the API caller can index back into the file).
        confidence: 0..1; the orchestrator uses this for ranking.
        sample_values: up to 3 representative cell values (for the
            UI's "Örnek değerler:" preview).
        metadata: detector-specific extras (e.g. ``locale``,
            ``currency``, ``is_pii``). Kept open-ended so each
            detector can stash what its UI consumer needs without
            adding fields to the dataclass.
    """

    field_name: FieldName
    column_name: str
    confidence: float
    sample_values: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
