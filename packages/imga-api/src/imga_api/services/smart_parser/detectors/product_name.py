"""ProductNameDetector — recognise product/item-name columns.

Sprint 8.3.8. Header signal + content heuristics: 10-80 char average
length, multi-word average. The Türkçe-recognisable check is
deliberately naive (a small frequency-of-common-letters proxy)
because real Türkçe morphology is out of scope; the 10% bonus only
nudges, it doesn't dominate.
"""

from __future__ import annotations

from typing import Final

from imga_api.services.smart_parser.base import (
    Detector,
    header_matches_any,
    take_samples,
)
from imga_api.services.smart_parser.types import DetectorResult, FieldName

_HEADER_PATTERNS: Final[tuple[str, ...]] = (
    "urun",
    "urun adi",
    "urun_adi",
    "product",
    "product name",
    "product_name",
    "item",
    "item name",
    "mal",
    "esya",
    "marka model",
    "model",
)

# Türkçe characters (folded forms) that show up far more in product
# names than in IDs/dates/numerics. A naive proxy — a real morphology
# would belong in imga-core, not the smart_parser.
_TR_TOKENS: Final[frozenset[str]] = frozenset(
    [
        "li",
        "lik",
        "siz",
        "ler",
        "lar",
        "in",
        "on",
        "ne",
        "yle",
    ]
)


class ProductNameDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.PRODUCT_NAME.value

    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        del all_columns
        header_hit = header_matches_any(column_name, _HEADER_PATTERNS)
        cleaned = [v.strip() for v in sample_values if v and v.strip()]

        if not cleaned:
            # Empty samples — only emit if header is unambiguous.
            if header_hit:
                return DetectorResult(
                    field_name=FieldName.PRODUCT_NAME,
                    column_name=column_name,
                    confidence=0.4,
                    sample_values=[],
                    metadata={"empty_samples": True},
                )
            return None

        avg_len = sum(len(v) for v in cleaned) / len(cleaned)
        avg_words = sum(len(v.split()) for v in cleaned) / len(cleaned)
        tr_signal = self._turkish_token_rate(cleaned)

        # Window check: 10-80 char range, ≥1.5 words on average.
        in_length_window = 10.0 <= avg_len <= 80.0
        is_multi_word = avg_words >= 1.5

        if not header_hit and not in_length_window:
            # No name signal AND content doesn't fit — bail out so the
            # detector doesn't false-positive over freeform review
            # text (which the existing review_text path handles).
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.4
        if in_length_window:
            confidence += 0.3
        if is_multi_word:
            confidence += 0.2
        if tr_signal >= 0.3:
            confidence += 0.1

        return DetectorResult(
            field_name=FieldName.PRODUCT_NAME,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
                "avg_length": round(avg_len, 1),
                "avg_words": round(avg_words, 1),
                "tr_token_rate": round(tr_signal, 2),
                "header_hit": header_hit,
            },
        )

    @staticmethod
    def _turkish_token_rate(values: list[str]) -> float:
        """Fraction of values that contain at least one common Türkçe
        suffix-like token. Naive but cheap — a real Türkçe-vs-other
        decision belongs in imga-core."""
        if not values:
            return 0.0
        hits = 0
        for v in values:
            tokens = {t.lower() for t in v.split() if t}
            if tokens & _TR_TOKENS:
                hits += 1
                continue
            # Also check token suffixes (e.g. "tişört" ends in
            # something but not exactly the suffix tokens).
            for t in v.lower().split():
                if any(t.endswith(suffix) for suffix in _TR_TOKENS):
                    hits += 1
                    break
        return hits / len(values)
