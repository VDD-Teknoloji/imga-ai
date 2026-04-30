"""Tests for normalize_turkish — Turkish-aware lower-casing — and the
review_text_hash digest used by the auto-ticket bridge."""

from __future__ import annotations

import hashlib
import unicodedata

from imga_core.text_utils import normalize_turkish, review_text_hash


class TestTurkishNormalization:
    def test_capital_i_with_dot_normalizes_to_ascii_i(self) -> None:
        """İADE -> iade, no combining dot."""
        result = normalize_turkish("İADE")
        assert result == "iade"
        # 4 codepoints, not 5: combining dot would have added one
        assert len(result) == 4

    def test_capital_i_without_dot_normalizes_to_dotless_i(self) -> None:
        """ISPARTA -> ısparta (Turkish dotless i)."""
        result = normalize_turkish("ISPARTA")
        assert result == "ısparta"

    def test_mixed_turkish_text(self) -> None:
        result = normalize_turkish("İptal etmek İSTİYORUM")
        assert result == "iptal etmek istiyorum"

    def test_already_lowercase_unchanged(self) -> None:
        result = normalize_turkish("kargom gelmedi")
        assert result == "kargom gelmedi"

    def test_other_turkish_chars_lowercase(self) -> None:
        result = normalize_turkish("ÇOK ŞİKAYET ETTİM")
        assert result == "çok şikayet ettim"

    def test_substring_match_works_after_normalize(self) -> None:
        """Regression: 'iade' substring used to fail on 'İade...'."""
        text = "İade etmek istiyorum"
        normalized = normalize_turkish(text)
        assert "iade" in normalized

    def test_iptal_substring_match(self) -> None:
        """Regression: 'iptal' substring used to fail on 'İPTAL'."""
        text = "Siparişimi İPTAL ettim"
        normalized = normalize_turkish(text)
        assert "iptal" in normalized

    def test_nfc_no_combining_chars(self) -> None:
        """Output should be NFC-composed; no decomposed combining marks."""
        result = normalize_turkish("İade")
        for char in result:
            # 'Mn' = Mark, Nonspacing (combining diacritic)
            assert unicodedata.category(char) != "Mn", (
                f"unexpected combining char {char!r} (U+{ord(char):04X}) in {result!r}"
            )

    def test_empty_string(self) -> None:
        assert normalize_turkish("") == ""

    def test_whitespace_only_preserved(self) -> None:
        assert normalize_turkish("   ") == "   "

    def test_no_turkish_chars(self) -> None:
        assert normalize_turkish("Hello World") == "hello world"

    def test_punctuation_preserved(self) -> None:
        assert normalize_turkish("İade istiyorum!") == "iade istiyorum!"

    def test_dotless_i_already_lowercase_unchanged(self) -> None:
        """ı stays ı; no special handling."""
        assert normalize_turkish("ışık") == "ışık"

    def test_dotted_i_already_lowercase_unchanged(self) -> None:
        """i stays i."""
        assert normalize_turkish("iptal") == "iptal"

    def test_mixed_dotted_and_dotless_capitals(self) -> None:
        """Both forms in the same text."""
        result = normalize_turkish("IRMAK İRTİBAT")
        assert result == "ırmak irtibat"


class TestReviewTextHash:
    """sha256 hex over normalize_turkish(text).strip(). Used by the
    auto-ticket bridge as the dedup key, so two submissions that
    differ only in casing or surrounding whitespace must collapse."""

    def test_hash_is_64_hex_chars(self) -> None:
        h = review_text_hash("Kargom gelmedi")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_casing_collapse(self) -> None:
        """KARGOM and kargom must produce the same hash."""
        a = review_text_hash("Kargom gelmedi")
        b = review_text_hash("KARGOM GELMEDİ")
        assert a == b

    def test_whitespace_padding_collapses(self) -> None:
        """Leading/trailing whitespace stripped before hashing."""
        a = review_text_hash("kargom gelmedi")
        b = review_text_hash("   kargom gelmedi\n")
        assert a == b

    def test_internal_whitespace_preserved(self) -> None:
        """A double space inside the text is NOT collapsed; only outer
        whitespace is stripped. Two-space text differs from one-space."""
        a = review_text_hash("kargom gelmedi")
        b = review_text_hash("kargom  gelmedi")
        assert a != b

    def test_different_texts_produce_different_hashes(self) -> None:
        a = review_text_hash("Kargom gelmedi")
        b = review_text_hash("Faturam yanlış geldi")
        assert a != b

    def test_matches_manual_sha256(self) -> None:
        """Spec: sha256(normalize_turkish(text).strip().encode('utf-8'))."""
        text = "  İade İSTİYORUM  "
        expected = hashlib.sha256(
            normalize_turkish(text).strip().encode("utf-8")
        ).hexdigest()
        assert review_text_hash(text) == expected

    def test_empty_string_has_known_hash(self) -> None:
        """sha256 of the empty string is a stable, well-known value."""
        empty_hash = (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )
        assert review_text_hash("") == empty_hash
        # Whitespace-only also collapses to empty after .strip().
        assert review_text_hash("   ") == empty_hash
