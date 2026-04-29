"""Behavioral tests for KeywordCategoryClassifier.

Per-category sample texts (Aşama 2 review requirement: every category gets
at least one positive case), plus edge cases for empty input, fallback,
multi-category, ranking, and confidence threshold logic.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from imga_core import KeywordCategoryClassifier


@pytest.fixture
def classifier() -> KeywordCategoryClassifier:
    return KeywordCategoryClassifier()


# --- Per-category positive cases -----------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_category"),
    [
        # kargo
        ("Kargom 5 gündür gelmedi, neredeyse kayboldu.", "kargo"),
        ("Kuryeci gelmedi, paketim nerede acaba?", "kargo"),
        # faturalama
        ("Faturam yanlış kesildi, fazla ücret alınmış.", "faturalama"),
        ("Kart bilgilerim kullanılmış, çift çekim oldu.", "faturalama"),
        # urun_kalitesi
        ("Ürün defolu geldi, dikiş bozuk ve kumaş kalitesi berbat.", "urun_kalitesi"),
        ("Sahte ürün gönderildi, orijinal değil bence taklit.", "urun_kalitesi"),
        # musteri_hizmetleri
        (
            "Müşteri hizmetleri telefonu kapattı, bağlanamıyorum, "
            "personel kaba davrandı.",
            "musteri_hizmetleri",
        ),
        # iade
        (
            "İade istiyorum, iade kabul edilmedi, geri ödeme yapılmadı.",
            "iade",
        ),
        # teknik_destek
        (
            "Uygulama açılmıyor, ekran beyaz, hata aldım, sayfa yenilenmiyor.",
            "teknik_destek",
        ),
        # siparis_sureci
        (
            "Siparişim hazırlanıyor diyor ama sevk edilmedi, depoda bekliyor.",
            "siparis_sureci",
        ),
        # pazarlama
        (
            "Yanıltıcı reklam, kampanya geçerli değil, kupon geçersiz, "
            "indirim kodu çalışmadı.",
            "pazarlama",
        ),
    ],
)
def test_per_category_sample_text(
    classifier: KeywordCategoryClassifier, text: str, expected_category: str
) -> None:
    result = classifier.classify(text)
    assert result.primary == expected_category, (
        f"text={text!r} expected primary={expected_category!r}, "
        f"got {result.primary!r} with matches={result.primary_matched_keywords}"
    )


# --- Empty / no-match -----------------------------------------------------


def test_empty_text_returns_belirsiz(classifier: KeywordCategoryClassifier) -> None:
    result = classifier.classify("")
    assert result.primary == "belirsiz"
    assert result.primary_confidence == 0.0
    assert result.requires_manual_review is True


def test_whitespace_only_returns_belirsiz(classifier: KeywordCategoryClassifier) -> None:
    result = classifier.classify("   \n  ")
    assert result.primary == "belirsiz"
    assert result.requires_manual_review is True


def test_no_keywords_match_returns_belirsiz(classifier: KeywordCategoryClassifier) -> None:
    result = classifier.classify("merhaba nasılsınız bugün hava güzel")
    assert result.primary == "belirsiz"
    assert result.requires_manual_review is True


# --- Confidence + manual review ------------------------------------------


def test_low_confidence_marks_for_manual_review() -> None:
    """Single-keyword hit with default min_confidence=0.3, divisor=5.0
    produces confidence 0.2, below threshold."""
    classifier = KeywordCategoryClassifier(min_confidence=0.3)
    result = classifier.classify("kargo")  # exactly one keyword
    assert result.primary == "kargo"
    assert result.primary_confidence == pytest.approx(0.2)
    assert result.requires_manual_review is True


def test_high_confidence_does_not_mark_for_review() -> None:
    classifier = KeywordCategoryClassifier(min_confidence=0.3)
    # 4 hits in iade -> confidence 0.8
    result = classifier.classify(
        "İade istiyorum, iade kargosu, iade kodu, iade etmek için aradım"
    )
    assert result.primary == "iade"
    assert result.primary_confidence >= 0.6
    assert result.requires_manual_review is False


def test_confidence_caps_at_one() -> None:
    classifier = KeywordCategoryClassifier(normalization_divisor=2.0)
    # Many iade keywords -> confidence should saturate at 1.0
    result = classifier.classify(
        "İade istiyorum, iade etmek, iade kabul edilmedi, "
        "iade reddedildi, iade kargosu, iade kodu"
    )
    assert result.primary_confidence == 1.0


# --- Multi-category ------------------------------------------------------


def test_multiple_categories_returns_secondaries(
    classifier: KeywordCategoryClassifier,
) -> None:
    text = (
        "Kargo geç geldi, ulaşmadı önce, sonra fatura yanlış kesildi, "
        "iade etmek istiyorum"
    )
    result = classifier.classify(text)
    assert len(result.secondaries) >= 1
    all_categories = {result.primary, *(s.category for s in result.secondaries)}
    # All three categories should appear among primary + secondaries
    assert {"kargo", "faturalama", "iade"}.issubset(all_categories)


def test_secondaries_sorted_by_confidence_descending(
    classifier: KeywordCategoryClassifier,
) -> None:
    text = (
        # Strong iade signal (4 hits)
        "İade istiyorum, iade kargosu, iade kodu, iade kabul edilmedi. "
        # One kargo signal
        "Kargo da gelmedi."
    )
    result = classifier.classify(text)
    assert result.primary == "iade"
    if result.secondaries:
        confidences = [s.confidence for s in result.secondaries]
        assert confidences == sorted(confidences, reverse=True), (
            f"Secondaries not sorted by confidence: {confidences}"
        )


def test_alphabetic_tie_break_when_hit_counts_equal(
    classifier: KeywordCategoryClassifier,
) -> None:
    """Equal hit counts: lower-alphabetic code wins primary."""
    # 'fatura' hits faturalama once, 'kargo' hits kargo once.
    # Alphabetic: 'faturalama' < 'kargo', so primary should be faturalama.
    result = classifier.classify("fatura ve kargo problemleri var")
    assert result.primary == "faturalama"


# --- Method + immutability ------------------------------------------------


def test_method_field_is_keyword(classifier: KeywordCategoryClassifier) -> None:
    result = classifier.classify("kargo gelmedi")
    assert result.method == "keyword"


def test_result_is_immutable(classifier: KeywordCategoryClassifier) -> None:
    result = classifier.classify("kargo gelmedi")
    with pytest.raises(ValidationError):
        result.primary = "iade"  # type: ignore[misc]


def test_matched_keywords_are_sorted(classifier: KeywordCategoryClassifier) -> None:
    """Deterministic order — same convention as override layers."""
    result = classifier.classify("kargo gelmedi kuryem ulaşmadı")
    matched = list(result.primary_matched_keywords)
    assert matched == sorted(matched)


# --- Batch ---------------------------------------------------------------


def test_classify_batch_preserves_order(classifier: KeywordCategoryClassifier) -> None:
    texts = [
        "kargo gelmedi",
        "iade istiyorum",
        "merhaba",
    ]
    results = classifier.classify_batch(texts)
    assert len(results) == 3
    assert results[0].primary == "kargo"
    assert results[1].primary == "iade"
    assert results[2].primary == "belirsiz"


def test_classify_batch_empty_list(classifier: KeywordCategoryClassifier) -> None:
    assert classifier.classify_batch([]) == []
