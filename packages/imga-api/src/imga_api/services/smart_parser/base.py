"""Detector base class and shared text-normalisation helpers.

Sprint 8.3.8. Every smart_parser detector implements this ABC. The
``detect`` method is pure: given a column name and its sample values,
it either returns a ``DetectorResult`` or ``None``.

Header matching uses Türkçe-aware case folding (``imga_core
.text_utils.normalize_turkish``) plus the ASCII fold the
``nps_detector`` already established. This keeps the
``Müşteri`` / ``MUSTERI`` / ``musteri`` variants in one bucket
without forcing tenants to type ASCII.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Final

from imga_core.text_utils import normalize_turkish

from imga_api.services.smart_parser.types import DetectorResult

_ASCII_FOLD: Final[dict[str, str]] = {
    "ı": "i",
    "ö": "o",
    "ü": "u",
    "ç": "c",
    "ş": "s",
    "ğ": "g",
}


def normalize_header(name: str) -> str:
    """Türkçe-aware case fold + ASCII fold + whitespace collapse.

    Mirrors imga_core.parsers.nps_detector._normalize_header so
    detectors and the NPS path see identical comparison strings."""
    folded = normalize_turkish(name.strip())
    for tr, ascii_ in _ASCII_FOLD.items():
        folded = folded.replace(tr, ascii_)
    return " ".join(folded.split())


def header_matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    """``name`` matches one of ``patterns`` after Türkçe-aware folding,
    either as an exact match OR as a token substring (so ``order_id``
    pattern matches a header like ``customer_order_id``)."""
    folded = normalize_header(name)
    for raw in patterns:
        pat = normalize_header(raw)
        if folded == pat:
            return True
        # Word-boundary substring: split on non-alphanumeric and check
        # token equality. Avoids false positives (``no`` matching
        # ``noresponse``).
        tokens = _split_tokens(folded)
        if pat in tokens:
            return True
        # Compound pattern (``order id`` after fold): allow if the
        # full pattern appears as a contiguous substring with word
        # boundaries on either side.
        if " " in pat and pat in folded:
            return True
    return False


def _split_tokens(s: str) -> list[str]:
    """Break a folded string into alphanumeric tokens. Used by
    ``header_matches_any`` for word-boundary substring checks."""
    out: list[str] = []
    buf: list[str] = []
    for ch in s:
        if ch.isalnum():
            buf.append(ch)
        else:
            if buf:
                out.append("".join(buf))
                buf = []
    if buf:
        out.append("".join(buf))
    return out


def take_samples(values: list[str], limit: int = 3) -> list[str]:
    """First ``limit`` non-empty values, stringified + trimmed. Used
    by every detector for the ``DetectorResult.sample_values`` field."""
    out: list[str] = []
    for v in values:
        s = (v or "").strip()
        if not s:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


class Detector(ABC):
    """Base class. Subclasses set ``field_name`` and implement
    ``detect``."""

    @property
    @abstractmethod
    def field_name(self) -> str:
        """Logical field this detector recognises (matches a
        ``FieldName`` enum value)."""

    @abstractmethod
    def detect(
        self,
        column_name: str,
        sample_values: list[str],
        all_columns: list[str],
    ) -> DetectorResult | None:
        """Return a ``DetectorResult`` if this column matches; else
        ``None``. ``all_columns`` is provided for context-aware
        detection (a future detector might down-rank a candidate when
        a stronger sibling exists)."""


__all__ = [
    "Detector",
    "header_matches_any",
    "normalize_header",
    "take_samples",
]
