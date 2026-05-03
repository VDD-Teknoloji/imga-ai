"""Unit coverage for imga_core.parsers.nps_detector.

No DB, no async — these test the pure-function detector + value parser
that the file_parser layers on top of. Aim is to lock the legacy 5
patterns + the Sprint 8.3.5 additions, plus the round-half-up + clamp
+ Turkish-fold + invalid-value semantics.
"""

from __future__ import annotations

import pytest
from imga_core.parsers import (
    NPS_COLUMN_PATTERNS,
    detect_nps_column,
    parse_nps_value,
)

# --- pattern catalog -------------------------------------------------


def test_legacy_5_patterns_are_present() -> None:
    """The cx_sentiment_dashboard ground truth — exact uppercase strings
    from app.py:825. The folded form (lowercase) is what the catalog
    stores, so we assert each is in NPS_COLUMN_PATTERNS via lowercase."""
    legacy = ("nps", "score", "puan", "net tavsiye skoru", "net promoter score")
    for p in legacy:
        assert p in NPS_COLUMN_PATTERNS, f"legacy pattern {p!r} dropped"


# --- detect_nps_column ----------------------------------------------


@pytest.mark.parametrize(
    "headers, expected",
    [
        # Direct match — original casing returned.
        (["Yorum", "NPS", "Tarih"], "NPS"),
        (["Yorum", "Score", "Tarih"], "Score"),
        (["Yorum", "PUAN", "Tarih"], "PUAN"),
        # Compound legacy.
        (["Yorum", "Net Promoter Score", "Tarih"], "Net Promoter Score"),
        (["Yorum", "NET TAVSİYE SKORU"], "NET TAVSİYE SKORU"),
        # Sprint 8.3.5 addition.
        (["Yorum", "Rating Score", "Tarih"], "Rating Score"),
        # Turkish-aware case folding ("Puanı" with possessive ı).
        (["Yorum", "Memnuniyet Puanı"], "Memnuniyet Puanı"),
        # First match wins (legacy ordering).
        (["NPS", "Score"], "NPS"),
    ],
)
def test_detect_returns_original_header_for_known_pattern(
    headers: list[str], expected: str
) -> None:
    assert detect_nps_column(headers) == expected


def test_detect_returns_none_for_no_nps_header() -> None:
    assert detect_nps_column(["Müşteri Yorumu", "Tarih", "Source"]) is None


def test_detect_collapses_internal_whitespace() -> None:
    """Headers like 'Rating  Score' (double space) fold to a single
    space and match 'rating score'."""
    assert detect_nps_column(["Müşteri Yorumu", "Rating  Score"]) == "Rating  Score"


def test_detect_handles_empty_headers_list() -> None:
    assert detect_nps_column([]) is None


# --- parse_nps_value ------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Integers in range.
        (0, 0),
        (5, 5),
        (10, 10),
        # Numeric strings.
        ("0", 0),
        ("8", 8),
        ("10", 10),
        ("  7  ", 7),
        # Floats — round-half-up (banker's rounding would give 8 for 8.5).
        (8.5, 9),
        (7.5, 8),
        (6.5, 7),
        (5.4, 5),
        ("8.5", 9),
        ("8.4", 8),
        # Float at exact boundary.
        (10.0, 10),
        (0.0, 0),
    ],
)
def test_parse_value_in_range(raw: object, expected: int) -> None:
    assert parse_nps_value(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "not a number",
        "8/10",  # Legacy float() raises; we match.
        "8 puan",
        "iyi",
        # Out of range — schema check would reject, parser drops.
        -1,
        11,
        100,
        # ROUND_HALF_UP rounds AWAY from zero: -0.5 → -1, 10.5 → 11,
        # both out of [0, 10] → None.
        -0.5,
        10.5,
        # NaN / Inf.
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_parse_invalid_returns_none(raw: object) -> None:
    assert parse_nps_value(raw) is None


def test_parse_negative_half_rounds_away_from_zero() -> None:
    """ROUND_HALF_UP on -0.5 yields -1 (away from zero), and -1 is
    out of range so the parser returns None. Locks the rounding mode
    so a future refactor doesn't silently flip semantics."""
    assert parse_nps_value(-0.5) is None
    # -0.49 rounds to 0 (in range).
    assert parse_nps_value(-0.49) == 0
    # -0.51 rounds to -1 (out of range).
    assert parse_nps_value(-0.51) is None


def test_parse_rejects_bool_silently() -> None:
    """bool subclasses int; without the explicit guard True would map
    to 1 and False to 0. CSV cells never carry Python bools so the
    safer default is to reject."""
    assert parse_nps_value(True) is None
    assert parse_nps_value(False) is None


def test_parse_clamps_above_ten() -> None:
    assert parse_nps_value(15) is None
    assert parse_nps_value("15") is None
    assert parse_nps_value(10.5) is None  # rounds to 11 → out of range
