"""End-to-end pipeline tests with the category classifier wired in."""

from __future__ import annotations

from imga_core import (
    AnalysisPipeline,
    AnalyzerPrediction,
    HybridClassifier,
    KeywordCategoryClassifier,
    SentimentAnalyzer,
)
from imga_core.llm.base import LLMProvider
from imga_core.models import LLMClassificationResult


class _StubAnalyzer(SentimentAnalyzer):
    """Returns NÖTR/0.0 — sentiment side stays neutral so category logic is the focus."""

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        return [AnalyzerPrediction(label="NÖTR", score=0.0) for _ in texts]


# --- No classifier configured -------------------------------------------


def test_no_classifier_means_categorization_is_none() -> None:
    p = AnalysisPipeline(analyzer=_StubAnalyzer())
    r = p.analyze("Kargom gelmedi")
    assert r.categorization is None


# --- Keyword-only classifier --------------------------------------------


def test_keyword_classifier_attaches_categorization() -> None:
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )
    r = p.analyze("Kargom gelmedi, kuryem ulaşmadı")
    assert r.categorization is not None
    assert r.categorization.primary == "kargo"
    assert r.categorization.method == "keyword"
    assert "kargo" in r.categorization.primary_matched_keywords


def test_keyword_classifier_belirsiz_for_unrelated_text() -> None:
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )
    r = p.analyze("Merhaba bugün hava güzel")
    assert r.categorization is not None
    assert r.categorization.primary == "belirsiz"
    assert r.categorization.requires_manual_review is True


def test_categorization_runs_alongside_sentiment_overrides() -> None:
    """Critical sentiment override + iade categorization must coexist."""
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )
    r = p.analyze("Polis çağırdım, hırsızlık yaptınız, iade istiyorum, iade kargosu")
    # Sentiment side: critical override fires
    assert r.sentiment_label == "NEGATIF"
    assert any(o.layer == "critical" for o in r.overrides_applied)
    # Category side: iade wins (more matches than 'belirsiz')
    assert r.categorization is not None
    assert r.categorization.primary == "iade"


# --- Hybrid classifier with fake LLM ------------------------------------


class _FakeLLM(LLMProvider):
    def classify(
        self, text: str, available_categories: list[str]
    ) -> LLMClassificationResult:
        return LLMClassificationResult(
            primary="teknik_destek",
            confidence=0.9,
            reasoning="Site bug",
            provider="gemini",
            model="m",
        )

    def health_check(self) -> bool:
        return True


def test_hybrid_classifier_routes_to_llm_on_low_confidence() -> None:
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=HybridClassifier(
            keyword_classifier=KeywordCategoryClassifier(),
            llm_provider=_FakeLLM(),
            confidence_threshold=0.7,
        ),
    )
    # Single 'kargo' hit -> conf 0.2 -> LLM kicks in -> teknik_destek
    r = p.analyze("kargo bir gariplik var")
    assert r.categorization is not None
    assert r.categorization.method == "ensemble"
    assert r.categorization.primary == "teknik_destek"


# --- Batch ---------------------------------------------------------------


def test_batch_classifies_each_text() -> None:
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )
    texts = [
        "kargo gelmedi",
        "iade istiyorum, iade kargosu",
        "merhaba",
    ]
    results = p.analyze_batch(texts)
    assert len(results) == 3
    assert results[0].categorization is not None
    assert results[0].categorization.primary == "kargo"
    assert results[1].categorization is not None
    assert results[1].categorization.primary == "iade"
    assert results[2].categorization is not None
    assert results[2].categorization.primary == "belirsiz"


def test_empty_batch_returns_empty() -> None:
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )
    assert p.analyze_batch([]) == []


# --- Result schema -------------------------------------------------------


def test_result_serializes_categorization_to_json() -> None:
    p = AnalysisPipeline(
        analyzer=_StubAnalyzer(),
        classifier=KeywordCategoryClassifier(),
    )
    r = p.analyze("kargo gelmedi")
    payload = r.model_dump_json()
    assert '"categorization"' in payload
    assert '"primary":"kargo"' in payload
    assert '"method":"keyword"' in payload
