"""Tests for normalize_turkish — Turkish-aware lower-casing."""

from __future__ import annotations

import unicodedata

from imga_core.text_utils import normalize_turkish


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
