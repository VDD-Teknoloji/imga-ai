"""HybridClassifier tests covering the keyword/LLM routing decisions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from imga_core import (
    HybridClassifier,
    KeywordCategoryClassifier,
    LLMProviderError,
)
from imga_core.llm.base import LLMProvider
from imga_core.models import LLMClassificationResult


class _FakeLLM(LLMProvider):
    """Test double for LLMProvider with controllable response."""

    def __init__(
        self,
        result: LLMClassificationResult | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.result = result
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, list[str]]] = []

    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        self.calls.append((text, available_categories))
        if self.raise_exc is not None:
            raise self.raise_exc
        assert self.result is not None
        return self.result

    def health_check(self) -> bool:
        return self.raise_exc is None


@pytest.fixture
def keyword_classifier() -> KeywordCategoryClassifier:
    return KeywordCategoryClassifier()


# --- Cheap path: keyword confident enough --------------------------------


def test_high_confidence_keyword_skips_llm(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    fake_llm = _FakeLLM(
        result=LLMClassificationResult(
            primary="iade",
            confidence=0.99,
            reasoning="should-not-be-called",
            provider="gemini",
            model="test",
        )
    )
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.5,
    )
    text = (
        "İade istiyorum, iade kargosu, iade kodu, iade kabul edilmedi, "
        "iade reddedildi"
    )
    result = hybrid.classify(text)
    assert result.primary == "iade"
    assert result.method == "keyword"
    assert fake_llm.calls == [], "LLM should not be invoked when keyword is confident"


# --- LLM fallback fires on low confidence --------------------------------


def test_low_confidence_calls_llm_and_merges(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    fake_llm = _FakeLLM(
        result=LLMClassificationResult(
            primary="teknik_destek",
            confidence=0.85,
            reasoning="Site bug'ından bahsediyor",
            provider="gemini",
            model="gemini-2.5-flash",
        )
    )
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.7,
    )
    # Single keyword hit ('kargo'): keyword conf=0.2, below 0.7 -> LLM called
    result = hybrid.classify("kargo bir gariplik var")
    assert len(fake_llm.calls) == 1
    assert result.method == "ensemble"
    assert result.primary == "teknik_destek"
    assert result.primary_confidence == pytest.approx(0.85)
    assert result.llm_result is not None
    assert result.llm_result.provider == "gemini"
    assert result.requires_manual_review is False


def test_ensemble_keeps_keyword_secondaries(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    fake_llm = _FakeLLM(
        result=LLMClassificationResult(
            primary="pazarlama",
            confidence=0.9,
            reasoning="...",
            provider="gemini",
            model="m",
        )
    )
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.7,
    )
    # Multi-category text but each weak — primary kargo conf=0.2, secondaries from keyword
    result = hybrid.classify("kargo geldi, fatura kesildi")
    keyword_only = keyword_classifier.classify("kargo geldi, fatura kesildi")
    assert result.secondaries == keyword_only.secondaries


# --- LLM unavailable / disabled ------------------------------------------


def test_no_llm_low_confidence_marks_for_review(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=None,
        confidence_threshold=0.7,
    )
    result = hybrid.classify("kargo")  # conf 0.2
    assert result.method == "keyword"
    assert result.requires_manual_review is True
    assert result.llm_result is None


def test_no_llm_high_confidence_no_review_needed(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=None,
        confidence_threshold=0.5,
    )
    text = (
        "İade istiyorum, iade kargosu, iade kodu, iade kabul edilmedi, "
        "iade reddedildi"
    )
    result = hybrid.classify(text)
    assert result.method == "keyword"
    assert result.requires_manual_review is False


# --- LLM failure paths ---------------------------------------------------


def test_llm_provider_error_falls_back_to_keyword(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    fake_llm = _FakeLLM(raise_exc=LLMProviderError("network down"))
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.7,
    )
    result = hybrid.classify("kargo")
    assert len(fake_llm.calls) == 1
    assert result.method == "keyword"  # fell back, did not switch to ensemble
    assert result.requires_manual_review is True
    assert result.primary == "kargo"


def test_unexpected_exception_propagates(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    """Non-LLMProviderError exceptions are NOT swallowed — those are bugs."""
    fake_llm = _FakeLLM(raise_exc=RuntimeError("logic bug"))
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.7,
    )
    with pytest.raises(RuntimeError, match="logic bug"):
        hybrid.classify("kargo")


# --- Edge cases ----------------------------------------------------------


def test_empty_text_does_not_call_llm(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    fake_llm = _FakeLLM(
        result=LLMClassificationResult(
            primary="x",
            confidence=0.5,
            reasoning="",
            provider="g",
            model="m",
        )
    )
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.7,
    )
    result = hybrid.classify("")
    assert fake_llm.calls == [], "LLM should not be called for empty input"
    assert result.primary == "belirsiz"
    assert result.requires_manual_review is True


def test_threshold_boundary_inclusive(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    """Confidence exactly at threshold should NOT trigger LLM."""
    fake_llm = MagicMock(spec=LLMProvider)
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.6,
    )
    # Text triggers exactly 3 iade keywords ('iade', 'iade istiyorum',
    # 'iade kargosu') -> conf 3/5 = 0.6, sat at threshold.
    result = hybrid.classify("iade istiyorum, iade kargosu")
    assert result.primary == "iade"
    assert result.primary_confidence == pytest.approx(0.6)
    fake_llm.classify.assert_not_called()


def test_available_categories_passed_to_llm(
    keyword_classifier: KeywordCategoryClassifier,
) -> None:
    fake_llm = _FakeLLM(
        result=LLMClassificationResult(
            primary="iade",
            confidence=0.9,
            reasoning="...",
            provider="g",
            model="m",
        )
    )
    custom_categories = ["kargo", "iade", "belirsiz"]
    hybrid = HybridClassifier(
        keyword_classifier=keyword_classifier,
        llm_provider=fake_llm,
        confidence_threshold=0.7,
        available_categories=custom_categories,
    )
    hybrid.classify("kargo")
    assert fake_llm.calls[0][1] == custom_categories
