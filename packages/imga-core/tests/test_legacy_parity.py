"""Dynamic parity test against legacy/app.py outputs.

Compares the new `AnalysisPipeline` against a snapshot of legacy outputs
(produced by `scripts/generate_legacy_snapshot.py`). The snapshot pins what
the legacy Streamlit prototype actually returned for each fixture text, so
this test catches behavioral drift that the static lexicon-size and
formula-equality tests would miss.

Skipped when `legacy_snapshot.json` is not present (e.g. on a fresh checkout
before someone runs the harness).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from imga_core import AnalysisPipeline, BertSentimentAnalyzer, SLAParams

SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "legacy_snapshot.json"
SCORE_TOLERANCE = 0.01

_LABEL_NORMALIZE = {
    "Pozitif": "POZITIF",
    "Nötr": "NÖTR",
    "Negatif": "NEGATIF",
    "POZITIF": "POZITIF",
    "NÖTR": "NÖTR",
    "NEGATIF": "NEGATIF",
}

_SLA_LABEL_PATTERN = re.compile(r"^SLA (Uyumlu|Aşımı)")


def _normalize_legacy_label(legacy_label: str) -> tuple[str, str | None]:
    """Map legacy's custom labels to (canonical_label, sla_detail).

    Legacy stores SLA hits as a custom Sentiment_Label like 'SLA Aşımı (5 Gün > 3)'
    or 'SLA Uyumlu (...)'. The new package puts the SLA string in `sla_detected`
    and keeps `sentiment_label` as POZITIF/NÖTR/NEGATIF. To compare:
        - If legacy label starts with 'SLA Uyumlu' -> NÖTR + that string
        - If legacy label starts with 'SLA Aşımı'  -> NEGATIF + that string
        - Otherwise normalize via map.
    """
    if _SLA_LABEL_PATTERN.match(legacy_label):
        canonical = "NEGATIF" if "Aşımı" in legacy_label else "NÖTR"
        return canonical, legacy_label
    return _LABEL_NORMALIZE.get(legacy_label, legacy_label), None


@pytest.fixture(scope="module")
def legacy_cases() -> list[dict[str, Any]]:
    if not SNAPSHOT_PATH.exists():
        pytest.skip(
            f"{SNAPSHOT_PATH.name} missing; "
            f"run `python scripts/generate_legacy_snapshot.py` first."
        )
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return list(payload.get("cases", []))


@pytest.fixture(scope="module")
def new_pipeline() -> AnalysisPipeline:
    """Real BERT analyzer + same SLA defaults as legacy run."""
    return AnalysisPipeline(
        analyzer=BertSentimentAnalyzer(),
        sla_params=SLAParams(max_shipping_days=3, max_warehouse_days=2),
    )


def _summary_keywords(s: str | None) -> set[str]:
    """Extract comparable comma-separated tokens from a summary string."""
    if not s:
        return set()
    body = s.removeprefix("📝 ").strip()
    return {part.strip() for part in body.split(",") if part.strip()}


def test_snapshot_count_matches_input(legacy_cases: list[dict[str, Any]]) -> None:
    """Sanity: the snapshot must contain every fixture input."""
    inputs_path = Path(__file__).parent / "fixtures" / "snapshot_inputs.json"
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    assert len(legacy_cases) == len(inputs["cases"]), (
        f"Snapshot has {len(legacy_cases)} cases, "
        f"inputs have {len(inputs['cases'])}. Re-run generate_legacy_snapshot.py."
    )


@pytest.mark.parametrize("case_idx", range(36))
def test_label_score_parity(
    legacy_cases: list[dict[str, Any]],
    new_pipeline: AnalysisPipeline,
    case_idx: int,
) -> None:
    """Per-case: new pipeline must produce same label and score as legacy."""
    if case_idx >= len(legacy_cases):
        pytest.skip(f"case_idx {case_idx} out of range")
    case = legacy_cases[case_idx]
    text = case["text"]
    expected_label, expected_sla = _normalize_legacy_label(case["legacy_label"])
    expected_score = case["legacy_score"]

    result = new_pipeline.analyze(text)

    assert result.sentiment_label == expected_label, (
        f"[{case['id']}] label drift: legacy {case['legacy_label']!r} -> "
        f"normalized {expected_label!r}, got {result.sentiment_label!r} "
        f"for text {text!r}"
    )
    assert abs(result.sentiment_score - expected_score) < SCORE_TOLERANCE, (
        f"[{case['id']}] score drift: legacy {expected_score}, "
        f"got {result.sentiment_score} (delta="
        f"{abs(result.sentiment_score - expected_score):.4f}) for text {text!r}"
    )
    if expected_sla is not None:
        assert result.sla_detected == expected_sla, (
            f"[{case['id']}] SLA detail drift: legacy {expected_sla!r}, "
            f"got {result.sla_detected!r}"
        )


@pytest.mark.parametrize("case_idx", range(36))
def test_company_perspective_parity(
    legacy_cases: list[dict[str, Any]],
    new_pipeline: AnalysisPipeline,
    case_idx: int,
) -> None:
    """Company perspective is rule-based; must match legacy."""
    if case_idx >= len(legacy_cases):
        pytest.skip(f"case_idx {case_idx} out of range")
    case = legacy_cases[case_idx]
    expected = case["legacy_company_perspective"]

    result = new_pipeline.analyze(case["text"])

    assert result.company_perspective == expected, (
        f"[{case['id']}] company perspective: legacy {expected!r}, "
        f"got {result.company_perspective!r}"
    )


# Cases where legacy's summary fallback hits the equal-length tie-break and
# its set iteration randomly picks a different top-4. The new package added
# an alphabetic tie-break (commit fix(core): summary determinism), so the
# winner differs deterministically. These are documented improvements, not
# parity bugs.
_LEGACY_SUMMARY_NONDETERMINISTIC_IDS = frozenset({"perspective_authority_request"})


@pytest.mark.parametrize("case_idx", range(36))
def test_summary_keyword_set_parity(
    legacy_cases: list[dict[str, Any]],
    new_pipeline: AnalysisPipeline,
    case_idx: int,
) -> None:
    """Summary set-equality (order differs: legacy declared, new alphabetic)."""
    if case_idx >= len(legacy_cases):
        pytest.skip(f"case_idx {case_idx} out of range")
    case = legacy_cases[case_idx]
    if case["id"] in _LEGACY_SUMMARY_NONDETERMINISTIC_IDS:
        pytest.xfail(
            f"[{case['id']}] legacy fallback longest-words has equal-length "
            "ties and no tie-break — its top-4 picks vary by PYTHONHASHSEED. "
            "New package sorts alphabetically, so deterministic but different."
        )
    expected_set = _summary_keywords(case["legacy_summary"])

    result = new_pipeline.analyze(case["text"])
    actual_set = _summary_keywords(result.summary)

    assert actual_set == expected_set, (
        f"[{case['id']}] summary keyword set differs:\n"
        f"  legacy: {sorted(expected_set)}\n"
        f"  new:    {sorted(actual_set)}\n"
        f"  text:   {case['text']!r}"
    )
