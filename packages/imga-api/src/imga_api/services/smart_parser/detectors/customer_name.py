"""CustomerNameDetector — recognise full-name columns + emit PII flag.

Sprint 8.3.8. Heuristic: 2-3 capitalised words on average, header
matches one of the Türkçe / English name patterns. ``is_pii=True``
goes onto the metadata so the orchestrator can surface a
``pii_warnings`` list and the frontend's PiiWarningBanner can demand
explicit user consent before the upload proceeds.
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
    "musteri",
    "musteri adi",
    "musteri_adi",
    "musteri ad",
    "ad soyad",
    "ad_soyad",
    "isim",
    "isim soyisim",
    "isim_soyisim",
    "ad",
    "soyad",
    "name",
    "full name",
    "full_name",
    "customer",
    "customer name",
    "customer_name",
)


class CustomerNameDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.CUSTOMER_NAME.value

    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        del all_columns
        header_hit = header_matches_any(column_name, _HEADER_PATTERNS)
        cleaned = [v.strip() for v in sample_values if v and v.strip()]

        # Header signal alone is enough to emit a low-confidence
        # result — the PII flag must surface even if the column is
        # mostly empty in the preview window.
        if not header_hit and not cleaned:
            return None

        capitalized_rate = self._capitalized_rate(cleaned) if cleaned else 0.0
        word_count_ok = self._word_count_in_range(cleaned) if cleaned else False

        if not header_hit and capitalized_rate < 0.5:
            # No header signal AND content doesn't look like names →
            # not a name column.
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.5
        if capitalized_rate >= 0.7:
            confidence += 0.3
        if word_count_ok:
            confidence += 0.2

        return DetectorResult(
            field_name=FieldName.CUSTOMER_NAME,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
                "is_pii": True,
                "capitalized_rate": round(capitalized_rate, 2),
                "word_count_ok": word_count_ok,
                "header_hit": header_hit,
            },
        )

    @staticmethod
    def _capitalized_rate(values: list[str]) -> float:
        if not values:
            return 0.0
        hits = 0
        for v in values:
            tokens = v.split()
            if not tokens:
                continue
            # Each non-trivial token should start with an uppercase
            # letter (Türkçe-aware: İ/I both count).
            if all(_starts_uppercase(t) for t in tokens if len(t) > 1):
                hits += 1
        return hits / len(values)

    @staticmethod
    def _word_count_in_range(values: list[str]) -> bool:
        if not values:
            return False
        avg = sum(len(v.split()) for v in values) / len(values)
        return 1.5 <= avg <= 4.0


def _starts_uppercase(token: str) -> bool:
    if not token:
        return False
    first = token[0]
    # ``str.isupper`` returns False on non-letters; explicitly check
    # the alpha-uppercase combo so digits / punctuation never
    # qualify a token as "Capitalized".
    return first.isalpha() and first.isupper()
