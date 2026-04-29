"""Smart Rules engine tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from imga_core import (
    AnalysisPipeline,
    AnalyzerPrediction,
    Rule,
    RuleEngine,
    SentimentAnalyzer,
)


class _StubAnalyzer(SentimentAnalyzer):
    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        return [AnalyzerPrediction(label="POZITIF", score=0.5) for _ in texts]


@pytest.fixture
def rules_file(tmp_path: Path) -> Path:
    payload = {
        "customer_rules": [
            {
                "keywords": ["online değişim", "buton yok"],
                "label": "Dijital Eksiklik Talebi",
            },
            {"keywords": ["geri arama"], "label": "Geri Arama Talebi"},
        ],
        "company_rules": [
            {"keywords": ["stok hatası", "temin edilemedi"], "label": "Stok Yönetimi"},
        ],
    }
    p = tmp_path / "cx_rules.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# --- Rule.from_dict --------------------------------------------------------


class TestRuleFromDict:
    def test_lowercases_keywords(self) -> None:
        r = Rule.from_dict({"keywords": ["İADE", "Para"], "label": "X"})
        assert r.keywords == ("i̇ade", "para") or r.keywords == ("iade", "para")

    def test_strips_empty_keywords(self) -> None:
        r = Rule.from_dict({"keywords": ["a", "", "  "], "label": "X"})
        assert r.keywords == ("a",)

    def test_rejects_non_list_keywords(self) -> None:
        with pytest.raises(ValueError):
            Rule.from_dict({"keywords": "iade", "label": "X"})

    def test_rejects_empty_label(self) -> None:
        with pytest.raises(ValueError):
            Rule.from_dict({"keywords": ["x"], "label": "  "})

    def test_matches_any_keyword(self) -> None:
        r = Rule.from_dict({"keywords": ["iade", "kargo"], "label": "X"})
        assert r.matches("müşteri iade istiyor") is True
        assert r.matches("kargo gecikti") is True
        assert r.matches("hava güzel") is False


# --- RuleEngine ------------------------------------------------------------


class TestRuleEngine:
    def test_no_path_yields_empty_ruleset(self) -> None:
        eng = RuleEngine(None)
        assert eng.ruleset.is_empty
        assert eng.classify_customer("anything") is None
        assert eng.classify_company("anything") is None

    def test_missing_file_yields_empty_ruleset(self, tmp_path: Path) -> None:
        eng = RuleEngine(tmp_path / "nope.json")
        assert eng.ruleset.is_empty

    def test_loads_valid_rules(self, rules_file: Path) -> None:
        eng = RuleEngine(rules_file)
        assert len(eng.ruleset.customer_rules) == 2
        assert len(eng.ruleset.company_rules) == 1

    def test_customer_rule_first_match_wins(self, rules_file: Path) -> None:
        eng = RuleEngine(rules_file)
        assert eng.classify_customer("online değişim talebi") == "Dijital Eksiklik Talebi"
        assert eng.classify_customer("Lütfen geri arama yapın") == "Geri Arama Talebi"

    def test_company_rule_match(self, rules_file: Path) -> None:
        eng = RuleEngine(rules_file)
        assert eng.classify_company("ürün temin edilemedi") == "Stok Yönetimi"

    def test_no_match_returns_none(self, rules_file: Path) -> None:
        eng = RuleEngine(rules_file)
        assert eng.classify_customer("hava güzel") is None
        assert eng.classify_company("hava güzel") is None

    def test_malformed_json_does_not_crash(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        eng = RuleEngine(bad)
        assert eng.ruleset.is_empty

    def test_partial_malformed_rules_skipped(self, tmp_path: Path) -> None:
        payload = {
            "customer_rules": [
                {"keywords": ["a"], "label": "Good"},
                {"keywords": "not-a-list", "label": "Bad"},   # malformed
                {"keywords": ["b"], "label": "Also Good"},
            ]
        }
        p = tmp_path / "mixed.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        eng = RuleEngine(p)
        labels = {r.label for r in eng.ruleset.customer_rules}
        assert labels == {"Good", "Also Good"}


# --- Pipeline integration --------------------------------------------------


class TestPipelineWithRules:
    def test_rule_overrides_default_perspective(self, rules_file: Path) -> None:
        p = AnalysisPipeline(analyzer=_StubAnalyzer(), rules_path=rules_file)
        r = p.analyze("Online değişim yapamadım, buton yok.")
        assert r.customer_perspective == "Dijital Eksiklik Talebi"

    def test_rule_overrides_default_company_perspective(self, rules_file: Path) -> None:
        p = AnalysisPipeline(analyzer=_StubAnalyzer(), rules_path=rules_file)
        r = p.analyze("Ürün temin edilemedi diye yazdılar.")
        assert r.company_perspective == "Stok Yönetimi"

    def test_falls_through_to_hardcoded_when_no_rule_matches(self, rules_file: Path) -> None:
        p = AnalysisPipeline(analyzer=_StubAnalyzer(), rules_path=rules_file)
        # Lowercase 'iade' so str.lower() doesn't have to map Turkish "İ"
        # (which would emit "i̇" with a combining dot — same caveat as legacy).
        r = p.analyze("iade istiyorum hakkımı kullanacağım.")
        assert r.customer_perspective == "İade Talebi"

    def test_no_rules_path_uses_only_hardcoded(self) -> None:
        p = AnalysisPipeline(analyzer=_StubAnalyzer())
        r = p.analyze("Şikayetçiyim")
        assert r.customer_perspective == "Resmi Şikayet"
