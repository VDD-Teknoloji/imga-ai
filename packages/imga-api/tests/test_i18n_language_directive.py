"""Sprint 12 i18n — language_directive (AI çıktı dili yönergesi).

Kurum dili 'en' ise system prompt'a güçlü bir İngilizce talimatı eklenir;
'tr'/None/bilinmeyen → boş (mevcut Türkçe promptlar korunur). SWOT/OKR/brifing
servisleri bunu resolve edilen system_prompt'un sonuna ekler.

2026-08-18 (migration 0042, WS1) — terminology_directive aynı dosyada,
aynı desende: kurum terim sözlüğü (tenants.terminology) doluysa system
prompt'un sonuna "AYNEN kullan" yönergesi eklenir; boş/None → boş.
"""

from imga_api.services.strategic_constants import (
    language_directive,
    terminology_directive,
)


def test_english_directive_present() -> None:
    d = language_directive("en")
    assert d, "en için yönerge boş olmamalı"
    assert "English" in d
    assert "Respond ONLY" in d


def test_turkish_none_unknown_empty() -> None:
    assert language_directive("tr") == ""
    assert language_directive(None) == ""
    assert language_directive("de") == ""  # bilinmeyen → güvenli boş


def test_terminology_directive_empty_or_none() -> None:
    assert terminology_directive(None) == ""
    assert terminology_directive([]) == ""
    # Yalnız boş term'lerden oluşan liste de boş sayılır.
    assert terminology_directive([{"term": "", "note": "not bos ama term yok"}]) == ""


def test_terminology_directive_renders_terms_with_and_without_note() -> None:
    d = terminology_directive(
        [
            {"term": "çok parçalı gönderi", "note": "birden fazla kutu"},
            {"term": "deforme"},
            {"term": "", "note": "boş term atlanır"},
        ]
    )
    assert d, "dolu sözlük boş dönmemeli"
    assert "AYNEN kullan" in d
    assert "- çok parçalı gönderi — birden fazla kutu" in d
    assert "- deforme" in d
    assert "boş term atlanır" not in d


def test_terminology_directive_ignores_malformed_entries() -> None:
    # JSONB kolonu şemasız; dict olmayan bir eleman (örn. string) 500'e
    # değil sessiz atlamaya düşmeli — dört stratejik servisin ortak yolu.
    d = terminology_directive(
        [
            "bozuk-girdi",  # type: ignore[list-item]
            {"term": "iade süreci", "note": "iade sureci degil"},
        ]
    )
    assert d
    assert "- iade süreci — iade sureci degil" in d
