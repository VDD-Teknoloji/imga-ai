"""Sanity tests for the per-category Turkish keyword lexicons.

Asserts shape (frozenset, lowercase, non-empty), minimum size, and
cross-category cleanup invariants — refund-money phrases live only in
iade, vendor cancel-state lives only in siparis_sureci, etc.
"""

from __future__ import annotations

import pytest

from imga_core.categories import GLOBAL_CATEGORY_CODES
from imga_core.categories.lexicons import (
    ALL_CATEGORY_KEYWORDS,
    FATURALAMA_KEYWORDS,
    IADE_KEYWORDS,
    KARGO_KEYWORDS,
    MUSTERI_HIZMETLERI_KEYWORDS,
    PAZARLAMA_KEYWORDS,
    SIPARIS_SURECI_KEYWORDS,
    TEKNIK_DESTEK_KEYWORDS,
    URUN_KALITESI_KEYWORDS,
)

# Min-size sanity — keeps anyone from accidentally emptying a lexicon.
_MIN_SIZE_PER_CATEGORY = 20


@pytest.mark.parametrize(
    ("code", "lex"),
    [
        ("kargo", KARGO_KEYWORDS),
        ("faturalama", FATURALAMA_KEYWORDS),
        ("urun_kalitesi", URUN_KALITESI_KEYWORDS),
        ("musteri_hizmetleri", MUSTERI_HIZMETLERI_KEYWORDS),
        ("iade", IADE_KEYWORDS),
        ("teknik_destek", TEKNIK_DESTEK_KEYWORDS),
        ("siparis_sureci", SIPARIS_SURECI_KEYWORDS),
        ("pazarlama", PAZARLAMA_KEYWORDS),
    ],
)
def test_lexicon_is_frozenset_and_meets_min_size(code: str, lex: frozenset[str]) -> None:
    assert isinstance(lex, frozenset), f"{code} lexicon must be a frozenset"
    assert len(lex) >= _MIN_SIZE_PER_CATEGORY, (
        f"{code} has only {len(lex)} keywords; min is {_MIN_SIZE_PER_CATEGORY}"
    )


@pytest.mark.parametrize(
    ("code", "lex"),
    list(ALL_CATEGORY_KEYWORDS.items()),
)
def test_all_keywords_are_lowercase(code: str, lex: frozenset[str]) -> None:
    """Match against text.lower() requires lowercase storage."""
    for word in lex:
        assert word == word.lower(), f"{code}: {word!r} has uppercase characters"


def test_all_keywords_are_non_empty_strings() -> None:
    for code, lex in ALL_CATEGORY_KEYWORDS.items():
        for word in lex:
            assert isinstance(word, str), f"{code}: {word!r} is not str"
            assert word.strip() == word, f"{code}: {word!r} has surrounding whitespace"
            assert len(word) > 0, f"{code}: empty keyword"


def test_all_codes_match_taxonomy() -> None:
    """ALL_CATEGORY_KEYWORDS keys must align with taxonomy codes (minus fallback)."""
    expected = {c for c in GLOBAL_CATEGORY_CODES if c != "belirsiz"}
    assert set(ALL_CATEGORY_KEYWORDS.keys()) == expected


# --- Cross-category cleanup invariants -----------------------------------


@pytest.mark.parametrize(
    "phrase",
    ["iade tutarı", "para iadesi", "iade ödeme"],
)
def test_refund_money_phrases_only_in_iade(phrase: str) -> None:
    """Refund-tied money phrases must not appear in faturalama."""
    assert phrase in IADE_KEYWORDS, f"{phrase!r} missing from iade"
    assert phrase not in FATURALAMA_KEYWORDS, f"{phrase!r} leaked into faturalama"


def test_sevk_edilmedi_only_in_siparis_sureci() -> None:
    """Vendor-side dispatch state belongs to siparis_sureci, not kargo."""
    assert "sevk edilmedi" in SIPARIS_SURECI_KEYWORDS
    assert "sevk edilmedi" not in KARGO_KEYWORDS


def test_iptal_edildi_only_in_siparis_sureci() -> None:
    """Vendor-cancelled state belongs to siparis_sureci, not iade."""
    assert "iptal edildi" in SIPARIS_SURECI_KEYWORDS
    assert "iptal edildi" not in IADE_KEYWORDS


@pytest.mark.parametrize(
    "phrase",
    ["iptal", "iptal istiyorum", "siparişimi iptal"],
)
def test_customer_cancel_only_in_iade(phrase: str) -> None:
    """Customer-initiated cancellation belongs to iade, not siparis_sureci."""
    assert phrase in IADE_KEYWORDS
    assert phrase not in SIPARIS_SURECI_KEYWORDS


def test_packaging_damage_in_urun_kalitesi_not_kargo() -> None:
    """'paket bozuk' / 'paket hasarlı' moved out of kargo (per Stage 2 review)."""
    assert "paket bozuk" not in KARGO_KEYWORDS
    assert "paket hasarlı" not in KARGO_KEYWORDS


def test_no_bare_overgeneric_keywords_in_teknik_destek() -> None:
    """Single-word noise that triggered too broadly was removed in cleanup."""
    for bare in ("sistem", "şifre", "çalışmıyor", "error", "bug", "api"):
        assert bare not in TEKNIK_DESTEK_KEYWORDS, (
            f"{bare!r} bare-token re-leaked into teknik_destek"
        )


def test_no_bare_overgeneric_keywords_in_pazarlama() -> None:
    for bare in ("aldatıcı", "yanıltıcı", "sosyal medya yanıltıcı"):
        assert bare not in PAZARLAMA_KEYWORDS, (
            f"{bare!r} bare-token re-leaked into pazarlama"
        )


# --- Cross-leak smoke check (informational) ------------------------------


def test_cross_leak_count_is_within_expected_bounds() -> None:
    """Track total keywords appearing in 2+ categories.

    Some overlap is intentional (e.g. 'değişim' could fit iade or
    musteri_hizmetleri in some texts), but excessive overlap makes the
    classifier ambiguous. This test pins an upper bound so accidental
    duplication during future edits gets flagged.
    """
    occurrence: dict[str, list[str]] = {}
    for code, lex in ALL_CATEGORY_KEYWORDS.items():
        for word in lex:
            occurrence.setdefault(word, []).append(code)
    multi_category = {w: cats for w, cats in occurrence.items() if len(cats) > 1}
    assert len(multi_category) <= 5, (
        f"Too many cross-category keywords ({len(multi_category)}): {multi_category}"
    )
