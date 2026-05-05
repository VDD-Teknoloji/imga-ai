"""TurkishDateDetector — date columns including Türkçe month-name forms.

Sprint 8.3.8. Recognises the three formats real Türkçe CSV exports
ship: ``DD/MM/YYYY``, ``DD.MM.YYYY``, and ``DD <Türkçe ay> YYYY``
(``1 Ocak 2026``). 4-digit year is mandatory — ``DD/MM/YY`` is
ambiguous enough that we'd rather miss the column than guess wrong.
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
    "tarih",
    "date",
    "created at",
    "created_at",
    "olusturma tarihi",
    "olusturma_tarihi",
    "siparis tarihi",
    "siparis_tarihi",
    "gun",
)

_TR_MONTHS: Final[tuple[str, ...]] = (
    "ocak",
    "subat",
    "mart",
    "nisan",
    "mayis",
    "haziran",
    "temmuz",
    "agustos",
    "eylul",
    "ekim",
    "kasim",
    "aralik",
)

# Three accepted shapes:
#   1) DD/MM/YYYY
#   2) DD.MM.YYYY
#   3) DD <Türkçe ay> YYYY  (case-folded)
_NUMERIC_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{1,2}[\./]\d{1,2}[\./]\d{4}$"
)
_TR_MONTH_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{1,2}\s+(?:" + "|".join(_TR_MONTHS) + r")\s+\d{4}$"
)


class TurkishDateDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.DATE.value

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
            if header_hit:
                return DetectorResult(
                    field_name=FieldName.DATE,
                    column_name=column_name,
                    confidence=0.4,
                    sample_values=[],
                    metadata={"empty_samples": True},
                )
            return None

        match_rate, formats = self._scan(cleaned)
        if not header_hit and match_rate < 0.7:
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.4
        confidence += 0.6 * match_rate

        return DetectorResult(
            field_name=FieldName.DATE,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
                "match_rate": round(match_rate, 2),
                "formats": sorted(formats),
                "header_hit": header_hit,
            },
        )

    @staticmethod
    def _scan(values: list[str]) -> tuple[float, set[str]]:
        formats: set[str] = set()
        hits = 0
        for raw in values:
            stripped = raw.strip()
            if _NUMERIC_DATE_RE.match(stripped):
                if "/" in stripped:
                    formats.add("DD/MM/YYYY")
                else:
                    formats.add("DD.MM.YYYY")
                hits += 1
                continue
            # Lowercase + ASCII-fold the month-name path so "Mayıs"
            # / "MAYIS" / "mayis" all match. The regex itself is
            # ASCII-only by design.
            folded = stripped.lower()
            for tr_ch, ascii_ch in (
                ("ı", "i"),
                ("ö", "o"),
                ("ü", "u"),
                ("ç", "c"),
                ("ş", "s"),
                ("ğ", "g"),
            ):
                folded = folded.replace(tr_ch, ascii_ch)
            if _TR_MONTH_RE.match(folded):
                formats.add("DD MMM YYYY (TR)")
                hits += 1
        return hits / len(values), formats
