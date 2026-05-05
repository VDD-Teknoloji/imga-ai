"""OrderIdDetector — recognise order/transaction identifier columns.

Sprint 8.3.8. Combination of header pattern + content shape:
alphanumeric uppercase 6-32 char strings. Confidence is split 50/50
between header match and content regex match-rate so a column whose
NAME smells like an order id but whose CONTENT is freeform text
won't outrank a real order-id column.
"""

from __future__ import annotations

import re
from typing import Final

from imga_api.services.smart_parser.base import (
    Detector,
    header_matches_any,
    take_samples,
)
from imga_api.services.smart_parser.types import DetectorResult, FieldName

_HEADER_PATTERNS: Final[tuple[str, ...]] = (
    "order",
    "order id",
    "order_id",
    "order number",
    "siparis",
    "siparis no",
    "siparis_no",
    "siparis numarasi",
    "fis",
    "fis no",
    "transaction id",
    "transaction_id",
)

# Allow letters / digits / dash / underscore. The 6-32 length window
# excludes review-text content (longer) and short codes like row
# numbers (1-3 chars).
_VALUE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9][A-Z0-9_-]{5,31}$")


class OrderIdDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.ORDER_ID.value

    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        del all_columns  # not used by this detector
        header_hit = header_matches_any(column_name, _HEADER_PATTERNS)
        match_rate = self._content_match_rate(sample_values)

        # Demand at least *one* signal beyond the trivial. Empty
        # samples + no header hit → None. Empty samples + strong
        # header hit → still emit at low confidence so the UI offers
        # the suggestion (a fresh upload may have NULL leading rows).
        if not header_hit and match_rate < 0.5:
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.5
        confidence += 0.5 * match_rate

        return DetectorResult(
            field_name=FieldName.ORDER_ID,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={"match_rate": match_rate, "header_hit": header_hit},
        )

    @staticmethod
    def _content_match_rate(values: list[str]) -> float:
        cleaned = [v.strip().upper() for v in values if v and v.strip()]
        if not cleaned:
            return 0.0
        hits = sum(1 for v in cleaned if _VALUE_RE.match(v))
        return hits / len(cleaned)
