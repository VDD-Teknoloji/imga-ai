"""PriceDetector — recognise monetary-amount columns.

Sprint 8.3.8. Header signal + numeric content + optional currency
symbol. Locale-aware: Türkçe formatting uses ``.`` as the thousand
separator and ``,`` as the decimal separator (``1.234,56``); English
uses the inverse (``1,234.56``). The detector emits the inferred
locale + currency in metadata so a future ingestion path can parse
correctly.
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
    "fiyat",
    "price",
    "tutar",
    "bedel",
    "ucret",
    "amount",
    "total",
    "toplam",
    "birim fiyat",
    "birim_fiyat",
    "unit price",
    "unit_price",
)

# Currency tokens — symbol or 3-letter code. Order doesn't matter
# (we report whichever shows up first).
_CURRENCY_TOKENS: Final[tuple[str, ...]] = (
    "₺",
    "$",
    "€",
    "£",
    "TL",
    "USD",
    "EUR",
    "GBP",
)

# Numeric matcher — accepts either Türkçe (1.234,56) or English
# (1,234.56) shapes plus bare decimals (12.50, 12,50, 12).
_NUMERIC_RE: Final[re.Pattern[str]] = re.compile(
    r"^-?\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{1,2})?$"
)


class PriceDetector(Detector):
    @property
    def field_name(self) -> str:
        return FieldName.PRICE.value

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
                    field_name=FieldName.PRICE,
                    column_name=column_name,
                    confidence=0.4,
                    sample_values=[],
                    metadata={"empty_samples": True},
                )
            return None

        numeric_rate, currency, locale = self._scan(cleaned)
        if not header_hit and numeric_rate < 0.7:
            return None

        confidence = 0.0
        if header_hit:
            confidence += 0.4
        confidence += 0.4 * numeric_rate
        if currency is not None:
            confidence += 0.2

        return DetectorResult(
            field_name=FieldName.PRICE,
            column_name=column_name,
            confidence=min(confidence, 1.0),
            sample_values=take_samples(sample_values),
            metadata={
                "numeric_rate": round(numeric_rate, 2),
                "currency": currency,
                "locale": locale,
                "header_hit": header_hit,
            },
        )

    @staticmethod
    def _scan(values: list[str]) -> tuple[float, str | None, str | None]:
        """Returns (numeric_match_rate, first_currency, locale).

        Locale heuristic: if the comma appears AFTER the period in
        any sample, the value is Türkçe (``1.234,56``); if the period
        appears AFTER the comma, English (``1,234.56``); otherwise
        ``None``."""
        currency: str | None = None
        locale: str | None = None
        hits = 0
        for raw in values:
            stripped = raw.strip()
            # Detect currency in raw string before stripping it.
            for token in _CURRENCY_TOKENS:
                if token in stripped:
                    currency = currency or token
                    stripped = stripped.replace(token, "").strip()
                    break

            if locale is None:
                comma_idx = stripped.rfind(",")
                period_idx = stripped.rfind(".")
                if comma_idx > period_idx and period_idx != -1:
                    locale = "tr_TR"
                elif period_idx > comma_idx and comma_idx != -1:
                    locale = "en_US"

            if _NUMERIC_RE.match(stripped):
                hits += 1
        return hits / len(values), currency, locale
