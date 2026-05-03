"""NPS column detection and value parsing for upload pipelines.

Sprint 8.3.5. Eski cx_sentiment_dashboard'da hardcoded 5 pattern vardı:
``NPS``, ``SCORE``, ``PUAN``, ``NET TAVSIYE SKORU``, ``NET PROMOTER SCORE``
(``app.py:825``, exact uppercase ``col.upper() in [...]`` karşılaştırması).
DEDAS sürümünde NPS yoktu.

Bu modülde legacy 5'i koruyoruz + Türkçe / İngilizce common varyantları
(``puanı`` possessive, ``skor`` alternative, ``rating`` / ``rating score``
common-in-English-surveys, ``memnuniyet`` / ``tavsiye`` puanı/skoru
alternative wordings) ekliyoruz. Eklemeler kullanıcıya raporlandı,
gereksizleri tamamen silmek bir line-edit.

Match stratejisi: ``normalize_turkish`` ile case + Turkish-aware folding
+ NFC normalize, sonra eşleşme. Bu, ``İçerik`` / ``içerik`` ve
``Puanı`` / ``PUANI`` / ``puani`` varyantlarının hepsini aynı kovaya
düşürür (file_parser'da ``_normalize_header`` aynı fonksiyonu kullanıyor —
tek bir folding kuralı, sürpriz yok).
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from imga_core.text_utils import normalize_turkish

# Legacy ground truth (cx_sentiment_dashboard/app.py:825 — col.upper() exact match).
# Normalized to lowercase Turkish-folded form for the detector's runtime
# comparison; the original strings would be e.g. "NPS", "SCORE", "PUAN",
# "NET TAVSIYE SKORU", "NET PROMOTER SCORE".
_LEGACY_PATTERNS: Final[tuple[str, ...]] = (
    "nps",
    "score",
    "puan",
    "net tavsiye skoru",
    "net promoter score",
)

# Sprint 8.3.5 additions — variants the legacy 5 don't cover but real
# tenants ship in their CSV/XLSX exports. Patterns are ASCII-folded
# (ı → i, ö → o, ü → u, ç → c, ş → s, ğ → g) so headers typed on either
# a Turkish or English keyboard ("Puanı" vs "Puani") both match the
# same entry. Order: legacy first → first-hit-wins keeps the original
# 5 dominant.
_ADDED_PATTERNS: Final[tuple[str, ...]] = (
    "nps score",
    "nps puani",
    "skor",
    "rating",
    "rating score",
    "net tavsiye puani",
    "memnuniyet skoru",
    "memnuniyet puani",
    "tavsiye puani",
    "tavsiye skoru",
)

# Combined pattern set used by detect_nps_column. Tuple (not set) so the
# match order is deterministic — first hit wins, legacy patterns first.
NPS_COLUMN_PATTERNS: Final[tuple[str, ...]] = _LEGACY_PATTERNS + _ADDED_PATTERNS

# Turkish-specific lowercase letters → ASCII fallback. Applied AFTER
# normalize_turkish so the header has already been case-folded with the
# Turkish I/İ rules; this last pass collapses dotless ı + the four
# diacritics so a Turkish-keyboard "Puanı" and an English-keyboard
# "Puani" land on the same comparison string.
_ASCII_FOLD: Final[dict[str, str]] = {
    "ı": "i",
    "ö": "o",
    "ü": "u",
    "ç": "c",
    "ş": "s",
    "ğ": "g",
}


def _normalize_header(name: str) -> str:
    """Strip + Turkish I/İ → ı/i + lowercase + NFC + ASCII-fold the
    Turkish-specific letters. Whitespace inside the header (e.g.
    "Rating  Score" with double space) collapses to a single space so
    "rating score" matches.
    """
    folded = normalize_turkish(name.strip())
    for tr, ascii_ in _ASCII_FOLD.items():
        folded = folded.replace(tr, ascii_)
    return " ".join(folded.split())


def detect_nps_column(headers: list[str]) -> str | None:
    """Return the *original* header string for the first NPS column hit,
    or None if none of the headers fold into a known pattern.

    Original casing is preserved in the return value because the
    downstream parser indexes columns by the literal header that came
    out of the CSV/XLSX file — the normalized form is only used for the
    comparison.
    """
    for original in headers:
        if _normalize_header(original) in NPS_COLUMN_PATTERNS:
            return original
    return None


def parse_nps_value(raw: object) -> int | None:
    """Convert a single cell value into an NPS score in [0, 10] or None.

    Rules:
      * None / empty string / whitespace-only → None.
      * Numeric (int, float, numeric-string) → ``ROUND_HALF_UP`` to int,
        then range-checked. The reviews check constraint
        ``ck_reviews_nps_score_range`` enforces the same bound at the DB
        layer; rejecting here is a friendlier error path.
      * NaN / Inf → None.
      * Out of range (< 0 or > 10) → None — legacy let -1 fall through
        to "Detractor", but our schema check would reject the insert,
        so we drop it at the parser instead of crashing the row.
      * Non-numeric strings ("8/10", "8 puan", "iyi") → None. Legacy
        used ``float(score)`` raw, which raises ValueError for these
        and the caller fell back to "Bilinmiyor"; we match that.

    The half-up rounding is via ``Decimal.quantize`` because Python's
    builtin ``round`` uses banker's rounding (round-half-to-even),
    which would map 0.5 → 0 and 1.5 → 2 — surprising semantics for
    user-facing NPS where 8.5 should round up to 9.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # bool is a subclass of int in Python; reject early to avoid
        # True → 1 / False → 0 silent coercion that wouldn't survive a
        # round-trip from a CSV cell.
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            as_float = float(stripped)
        except ValueError:
            return None
    elif isinstance(raw, (int, float)):
        as_float = float(raw)
    else:
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    rounded = int(
        Decimal(str(as_float)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    if rounded < 0 or rounded > 10:
        return None
    return rounded


__all__ = ["NPS_COLUMN_PATTERNS", "detect_nps_column", "parse_nps_value"]
