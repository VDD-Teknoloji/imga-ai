"""EmployeeNameDetector — recognise the 5th business dimension column
(``entered_by``): the employee who logged the review.

2026-08-18 (migration 0042) "büyük paket" WS2. Modelled on
``CustomerNameDetector`` (same header + capitalisation heuristic) with
one deliberate difference: ``is_pii`` is False here.

``CustomerNameDetector``'s PII banner exists because the product does
NOT want to silently store a customer's full name — the user has to
consent. ``entered_by`` is the opposite case: migration 0042 added it
as a DELIBERATE, product-requested 5th dimension (the quality report's
employee-based breakdown depends on it). Firing the same consent
banner on the very column this feature asks the tenant to map would
be a confusing false alarm, not a safeguard — so this detector never
sets ``is_pii``.
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
    "calisan",
    "calisan adi",
    "calisan_adi",
    "personel",
    "personel adi",
    "personel_adi",
    "temsilci",
    "temsilci adi",
    "ekleyen",
    "giren",
    "kaydeden",
    "agent",
    "agent name",
    "employee",
    "employee name",
    "employee_name",
    "girdi",
    "veri girisi",
)


class EmployeeNameDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.EMPLOYEE_NAME.value

    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        del all_columns
        header_hit = header_matches_any(column_name, _HEADER_PATTERNS)
        cleaned = [v.strip() for v in sample_values if v and v.strip()]

        # CustomerNameDetector'daki gibi: header sinyali tek başına
        # düşük-güvenilirlikli bir sonuç üretmeye yeter (kolon boş
        # örneklem penceresinde bile öneri sunulsun).
        if not header_hit and not cleaned:
            return None

        capitalized_rate = self._capitalized_rate(cleaned) if cleaned else 0.0
        word_count_ok = self._word_count_in_range(cleaned) if cleaned else False

        if not header_hit and capitalized_rate < 0.5:
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.5
        if capitalized_rate >= 0.7:
            confidence += 0.3
        if word_count_ok:
            confidence += 0.2

        return DetectorResult(
            field_name=FieldName.EMPLOYEE_NAME,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
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
    return first.isalpha() and first.isupper()
