"""Lexicon presence + size + immutability tests."""

from __future__ import annotations

from imga_core.lexicons import (
    CRITICAL_KEYWORDS,
    TIER1_SENTIMENT,
    TIER2_ISSUES,
    TIER3_FAILURES,
)


def test_lexicons_are_frozensets() -> None:
    assert isinstance(CRITICAL_KEYWORDS, frozenset)
    assert isinstance(TIER1_SENTIMENT, frozenset)
    assert isinstance(TIER2_ISSUES, frozenset)
    assert isinstance(TIER3_FAILURES, frozenset)


def test_lexicon_sizes_match_legacy() -> None:
    """Counts MUST match legacy/app.py for behavioral parity."""
    assert len(CRITICAL_KEYWORDS) == 15
    assert len(TIER1_SENTIMENT) == 22
    assert len(TIER2_ISSUES) == 30
    assert len(TIER3_FAILURES) == 13


def test_lexicons_disjoint_for_overrides() -> None:
    """Critical and Tier-1 should not overlap (different override scores)."""
    assert CRITICAL_KEYWORDS.isdisjoint(TIER1_SENTIMENT)


def test_critical_keywords_contains_known_examples() -> None:
    for word in ("hırsızlık", "polis", "dava", "tehdit"):
        assert word in CRITICAL_KEYWORDS


def test_tier1_contains_known_adjectives() -> None:
    for word in ("rezalet", "berbat", "iğrenç"):
        assert word in TIER1_SENTIMENT


def test_tier2_contains_operational_keywords() -> None:
    for word in ("iade", "kargo", "defolu"):
        assert word in TIER2_ISSUES


def test_tier3_contains_failure_verbs() -> None:
    for word in ("gelmedi", "ulaşmadı", "alamadım"):
        assert word in TIER3_FAILURES


def test_all_keywords_lowercase() -> None:
    """Override matching uses .lower() — lexicons must be pre-normalized."""
    for lex in (CRITICAL_KEYWORDS, TIER1_SENTIMENT, TIER2_ISSUES, TIER3_FAILURES):
        for word in lex:
            assert word == word.lower(), f"{word!r} is not lowercase"
