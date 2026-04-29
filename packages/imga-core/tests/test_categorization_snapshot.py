"""Categorization snapshot — runs the keyword classifier against every
fixture text in snapshot_inputs.json and checks the primary category.

Legacy parity tests cover sentiment; this file is the category twin.
We don't add `expected_category` to the JSON fixture itself so the
legacy parity machinery stays clean — instead the mapping lives here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from imga_core import KeywordCategoryClassifier

SNAPSHOT_INPUTS = (
    Path(__file__).parent / "fixtures" / "snapshot_inputs.json"
)

# Expected primary category per fixture id.
#
# Sprint 6.10 fixed the Turkish capital "İ" -> combining-dot bug via
# imga_core.text_utils.normalize_turkish, so 'iade' substring now matches
# inside "İade". perspective_iade_request was previously pinned to
# 'belirsiz' for that reason; now correctly returns 'iade'.
# tier1_02, tier1_04, perspective_authority_request still resolve to
# 'belirsiz' but for a different reason: their salient words ('personel',
# 'yetkili') are not in the per-category lexicons (only fully-formed
# phrases like 'personel kaba' or 'yetkili istedim' are).
EXPECTED_CATEGORY_BY_ID: dict[str, str] = {
    # Generic crisis texts — no business unit clear from words alone.
    "critical_01": "belirsiz",
    "critical_02": "belirsiz",
    "critical_03": "belirsiz",
    "critical_04": "belirsiz",
    "critical_05": "belirsiz",
    # Tier-1 — adjective-heavy texts; only 'paketleme' gives a hint here.
    "tier1_01": "belirsiz",
    "tier1_02": "belirsiz",  # 'İlgisiz' starts with İ → lower bug
    "tier1_03": "siparis_sureci",  # 'paketleme' wins
    "tier1_04": "belirsiz",  # 'Çözümsüz', 'yetersiz personel' don't pattern-match
    "tier1_05": "belirsiz",
    # Shipping SLA cases
    "sla_breach_shipping_01": "kargo",
    "sla_breach_shipping_02": "kargo",
    "sla_compliant_01": "kargo",
    "sla_warehouse_breach": "siparis_sureci",
    "sla_compliant_warehouse": "siparis_sureci",
    "sla_breach_long_shipping": "kargo",
    "sla_breach_2_weeks": "kargo",
    # Tier-2 fallback
    "tier2_fallback_01": "faturalama",  # 'fatura'+'para'+'yatmadı'  (İade -> İ bug)
    "tier2_fallback_02": "iade",  # 'değişim' wins (defolu+değişim hit but iade alphabetic)
    "tier2_fallback_kargo_gecikme": "kargo",
    "tier2_fallback_yanlis_urun": "kargo",  # 'gönderdi'/'yanlış ürün' tie -> kargo alpha-wins
    # Pure BERT — generic feedback
    "pure_bert_positive_01": "belirsiz",
    "pure_bert_positive_02": "belirsiz",
    "pure_bert_positive_03": "belirsiz",
    "pure_bert_positive_04": "kargo",
    "pure_bert_negative_01": "belirsiz",
    "pure_bert_negative_02": "urun_kalitesi",  # 'kırık' false-positive in 'hayal kırıklığı'
    "neutral_descriptive": "belirsiz",
    "borderline_short_neutral": "belirsiz",
    # Perspective-flagged
    "perspective_iade_request": "iade",  # Sprint 6.10 fix: İade now matches
    "perspective_complaint": "musteri_hizmetleri",
    "perspective_company_logistics": "kargo",
    "perspective_company_quality": "urun_kalitesi",
    "perspective_cancel_request": "siparis_sureci",  # 'sipariş' family wins over 'iptal'
    "perspective_authority_request": "belirsiz",  # all-İ-prefixed sentence
    "company_personnel": "musteri_hizmetleri",
}


@pytest.fixture(scope="module")
def fixture_cases() -> list[dict[str, str]]:
    payload = json.loads(SNAPSHOT_INPUTS.read_text(encoding="utf-8"))
    return list(payload.get("cases", []))


@pytest.fixture(scope="module")
def classifier() -> KeywordCategoryClassifier:
    return KeywordCategoryClassifier()


def test_expected_categories_cover_all_fixture_ids(
    fixture_cases: list[dict[str, str]],
) -> None:
    """Every fixture id must have an entry in EXPECTED_CATEGORY_BY_ID."""
    fixture_ids = {c["id"] for c in fixture_cases}
    expected_ids = set(EXPECTED_CATEGORY_BY_ID.keys())
    assert fixture_ids == expected_ids, (
        f"Coverage mismatch: missing={fixture_ids - expected_ids}, "
        f"stale={expected_ids - fixture_ids}"
    )


@pytest.mark.parametrize("case_id", list(EXPECTED_CATEGORY_BY_ID.keys()))
def test_keyword_categorization_matches_expected(
    fixture_cases: list[dict[str, str]],
    classifier: KeywordCategoryClassifier,
    case_id: str,
) -> None:
    case = next((c for c in fixture_cases if c["id"] == case_id), None)
    assert case is not None, f"Fixture {case_id} not found"

    expected = EXPECTED_CATEGORY_BY_ID[case_id]
    result = classifier.classify(case["text"])
    assert result.primary == expected, (
        f"[{case_id}] text={case['text']!r} expected category {expected!r}, "
        f"got {result.primary!r} (matches={result.primary_matched_keywords})"
    )
