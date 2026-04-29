"""Per-override-layer tests: trigger + non-trigger cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from imga_core.config import (
    CRITICAL_OVERRIDE_SCORE,
    SLA_BREACH_SCORE,
    SLA_COMPLIANT_SCORE,
    TIER1_OVERRIDE_SCORE,
    TIER2_FALLBACK_SCORE,
)
from imga_core.overrides import (
    KnowledgeBase,
    SLAParams,
    apply_critical_override,
    apply_sla_override,
    apply_tier1_override,
    apply_tier2_fallback,
)

# --- Critical --------------------------------------------------------------


class TestCriticalOverride:
    def test_fires_on_legal_keyword(self) -> None:
        hit = apply_critical_override("Bana karşı dava açılacakmış")
        assert hit is not None
        assert hit.layer == "critical"
        assert hit.score == CRITICAL_OVERRIDE_SCORE
        assert "dava" in hit.matched_keywords

    def test_fires_on_security_keyword(self) -> None:
        hit = apply_critical_override("Mağazada hırsızlıkla suçlandım, polis çağırdılar")
        assert hit is not None
        assert {"hırsız", "hırsızlık", "polis"}.issubset(set(hit.matched_keywords))

    def test_no_match_returns_none(self) -> None:
        assert apply_critical_override("Güzel bir alışveriş deneyimiydi") is None

    def test_empty_text_returns_none(self) -> None:
        assert apply_critical_override("") is None

    def test_case_insensitive(self) -> None:
        assert apply_critical_override("POLİS çağrıldı") is not None or \
               apply_critical_override("POLIS çağrıldı") is not None


# --- Tier-1 ----------------------------------------------------------------


class TestTier1Override:
    def test_fires_on_strong_negative_adjective(self) -> None:
        hit = apply_tier1_override("rezalet bir hizmet, berbat ürün")
        assert hit is not None
        assert hit.layer == "tier1"
        assert hit.score == TIER1_OVERRIDE_SCORE
        assert {"rezalet", "berbat"}.issubset(set(hit.matched_keywords))

    def test_no_match_returns_none(self) -> None:
        assert apply_tier1_override("ürün geldi, kullanıyorum") is None


# --- Tier-2 ----------------------------------------------------------------


class TestTier2Fallback:
    def test_fires_when_score_above_threshold(self) -> None:
        hit = apply_tier2_fallback("kargo gecikti, iade istiyorum", current_score=0.3)
        assert hit is not None
        assert hit.layer == "tier2"
        assert hit.score == TIER2_FALLBACK_SCORE

    def test_skipped_when_already_negative(self) -> None:
        # Score below trigger threshold means we trust the prior layer.
        assert apply_tier2_fallback("kargo gecikti", current_score=-0.5) is None

    def test_no_keyword_match_returns_none(self) -> None:
        assert apply_tier2_fallback("güzel ürün", current_score=0.5) is None


# --- SLA -------------------------------------------------------------------


class TestSLAOverride:
    def test_breach_in_shipping_context(self) -> None:
        hit = apply_sla_override("kargom 5 gündür gelmedi", SLAParams(max_shipping_days=3))
        assert hit is not None
        assert hit.layer == "sla"
        assert hit.score == SLA_BREACH_SCORE
        assert hit.detail is not None and "Aşımı" in hit.detail

    def test_compliant_in_shipping_context(self) -> None:
        hit = apply_sla_override("kargom 2 gündür bekliyorum", SLAParams(max_shipping_days=3))
        assert hit is not None
        assert hit.score == SLA_COMPLIANT_SCORE
        assert hit.detail is not None and "Uyumlu" in hit.detail

    def test_warehouse_context_uses_warehouse_limit(self) -> None:
        hit = apply_sla_override("paket 3 gün depoda bekledi", SLAParams(max_warehouse_days=2))
        assert hit is not None
        assert hit.score == SLA_BREACH_SCORE

    def test_no_duration_returns_none(self) -> None:
        assert apply_sla_override("kargo geldi") is None

    def test_no_context_keyword_returns_none(self) -> None:
        # "5 gün" present but no shipping/warehouse context word
        assert apply_sla_override("5 gün önce evlendim") is None

    def test_week_to_days_conversion(self) -> None:
        hit = apply_sla_override("siparişim 1 hafta oldu, gelmedi", SLAParams(max_shipping_days=3))
        assert hit is not None
        # 1 hafta = 7 days > 3 limit
        assert hit.score == SLA_BREACH_SCORE
        assert hit.detail is not None and "7" in hit.detail


# --- Knowledge Base --------------------------------------------------------


class TestKnowledgeBase:
    def test_no_path_returns_zero_size(self) -> None:
        kb = KnowledgeBase(None)
        assert kb.size == 0
        assert kb.lookup("anything") is None

    def test_missing_file_returns_zero_size(self, tmp_path: Path) -> None:
        kb = KnowledgeBase(tmp_path / "does_not_exist.csv")
        assert kb.size == 0

    def test_loads_valid_csv(self, tmp_kb_csv: Path) -> None:
        kb = KnowledgeBase(tmp_kb_csv)
        assert kb.size == 2

    def test_lookup_hit_returns_canonical_label(self, tmp_kb_csv: Path) -> None:
        kb = KnowledgeBase(tmp_kb_csv)
        hit = kb.lookup("Bu ürün harikaydı çok memnunum")
        assert hit is not None
        assert hit.layer == "knowledge_base"
        assert hit.score > 0  # Pozitif

    def test_lookup_negative_label(self, tmp_kb_csv: Path) -> None:
        kb = KnowledgeBase(tmp_kb_csv)
        hit = kb.lookup("Hiç beğenmedim berbat")
        assert hit is not None
        assert hit.score < 0

    def test_lookup_miss_returns_none(self, tmp_kb_csv: Path) -> None:
        kb = KnowledgeBase(tmp_kb_csv)
        assert kb.lookup("an unrelated review") is None

    def test_malformed_csv_does_not_crash(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        kb = KnowledgeBase(bad)
        assert kb.size == 0


# --- Edge cases ------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [apply_critical_override, apply_tier1_override],
)
def test_overrides_handle_empty_string(fn) -> None:  # type: ignore[no-untyped-def]
    assert fn("") is None
