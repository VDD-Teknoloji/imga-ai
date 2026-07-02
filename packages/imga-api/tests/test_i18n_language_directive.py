"""Sprint 12 i18n — language_directive (AI çıktı dili yönergesi).

Kurum dili 'en' ise system prompt'a güçlü bir İngilizce talimatı eklenir;
'tr'/None/bilinmeyen → boş (mevcut Türkçe promptlar korunur). SWOT/OKR/brifing
servisleri bunu resolve edilen system_prompt'un sonuna ekler.
"""

from imga_api.services.strategic_constants import language_directive


def test_english_directive_present() -> None:
    d = language_directive("en")
    assert d, "en için yönerge boş olmamalı"
    assert "English" in d
    assert "Respond ONLY" in d


def test_turkish_none_unknown_empty() -> None:
    assert language_directive("tr") == ""
    assert language_directive(None) == ""
    assert language_directive("de") == ""  # bilinmeyen → güvenli boş
