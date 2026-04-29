"""Pipeline orchestration tests using a FakeAnalyzer (no BERT load)."""

from __future__ import annotations

from imga_core import (
    AnalysisPipeline,
    AnalysisResult,
    AnalyzerPrediction,
    SentimentAnalyzer,
)
from imga_core.config import (
    CRITICAL_OVERRIDE_SCORE,
    SLA_BREACH_SCORE,
    TIER1_OVERRIDE_SCORE,
    TIER2_FALLBACK_SCORE,
)


class FakeAnalyzer(SentimentAnalyzer):
    """Returns POZITIF 0.5 for everything (so post-BERT layers have room to fire)."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        self.calls.append(list(texts))
        return [AnalyzerPrediction(label="POZITIF", score=0.5) for _ in texts]


class FakeNeutralAnalyzer(SentimentAnalyzer):
    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        return [AnalyzerPrediction(label="NÖTR", score=0.0) for _ in texts]


def test_critical_override_short_circuits_bert() -> None:
    fake = FakeAnalyzer()
    p = AnalysisPipeline(analyzer=fake)
    r = p.analyze("polis çağrılacakmış")
    assert r.sentiment_label == "NEGATIF"
    assert r.sentiment_score == CRITICAL_OVERRIDE_SCORE
    assert any(o.layer == "critical" for o in r.overrides_applied)
    assert fake.calls == [], "BERT must not be called when critical fires"


def test_tier1_override_short_circuits_bert() -> None:
    fake = FakeAnalyzer()
    p = AnalysisPipeline(analyzer=fake)
    r = p.analyze("rezalet bir deneyim")
    assert r.sentiment_score == TIER1_OVERRIDE_SCORE
    assert fake.calls == []


def test_pure_bert_passthrough_when_no_overrides() -> None:
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    r = p.analyze("ürün geldi, idare eder")
    assert r.sentiment_label == "POZITIF"
    assert r.sentiment_score == 0.5
    assert r.overrides_applied == []


def test_sla_override_modifies_post_bert() -> None:
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    r = p.analyze("siparişim 5 gündür kargoda bekliyorum")
    assert r.sentiment_score == SLA_BREACH_SCORE
    assert r.sentiment_label == "NEGATIF"
    assert r.sla_detected is not None
    assert any(o.layer == "sla" for o in r.overrides_applied)


def test_tier2_fallback_when_bert_misses_negative() -> None:
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    r = p.analyze("iade ettim ama param yatmadı henüz")
    assert r.sentiment_score == TIER2_FALLBACK_SCORE
    assert r.sentiment_label == "NEGATIF"
    assert any(o.layer == "tier2" for o in r.overrides_applied)


def test_tier2_does_not_fire_when_sla_already_did() -> None:
    """SLA fires first; tier2 is gated behind SLA being absent."""
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    # Both an SLA trigger ("kargo 5 gün") and a tier2 keyword ("iade") present.
    r = p.analyze("kargom 5 gündür gelmedi, iade istiyorum")
    layers = [o.layer for o in r.overrides_applied]
    assert "sla" in layers
    assert "tier2" not in layers


def test_batch_calls_bert_once_for_all_non_overridden() -> None:
    fake = FakeAnalyzer()
    p = AnalysisPipeline(analyzer=fake)
    texts = [
        "polis arandı",            # critical -> skip BERT
        "rezalet hizmet",          # tier1 -> skip BERT
        "güzel ürün",              # BERT
        "fena değil",              # BERT
    ]
    results = p.analyze_batch(texts)
    assert len(results) == 4
    assert len(fake.calls) == 1
    assert len(fake.calls[0]) == 2  # only the two non-overridden texts


def test_empty_batch_returns_empty() -> None:
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    assert p.analyze_batch([]) == []


def test_summary_and_perspectives_populated() -> None:
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    r = p.analyze("iade istiyorum, kargom da gelmedi")
    assert r.summary is not None and "📝" in r.summary
    assert r.customer_perspective == "İade Talebi"
    assert r.company_perspective == "Lojistik / Kargo Firması Hatası"


def test_risk_class_matches_label() -> None:
    p = AnalysisPipeline(analyzer=FakeNeutralAnalyzer())
    r = p.analyze("sıradan bir yorum")
    assert r.risk_class == r.sentiment_label


def test_result_validates_against_pydantic_schema() -> None:
    """End-to-end pydantic validation: dump -> reload roundtrip."""
    p = AnalysisPipeline(analyzer=FakeAnalyzer())
    r = p.analyze("ürün")
    payload = r.model_dump_json()
    AnalysisResult.model_validate_json(payload)
