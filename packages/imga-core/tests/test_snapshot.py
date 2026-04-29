"""Behavioral parity snapshot tests.

Two flavors:

1. Override-only cases (`bert_required=false`): run without loading the BERT
   model. These pin exact scores and labels for deterministic override layers.

2. BERT-dependent cases (`bert_required=true`): require the actual model and
   are gated behind the `slow` marker. Skipped by default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from imga_core import AnalysisPipeline, AnalyzerPrediction, SentimentAnalyzer

FIXTURE_FILE = "snapshot_inputs.json"
SCORE_TOLERANCE = 0.01


def _load_cases(fixtures_dir: Path) -> list[dict[str, Any]]:
    path = fixtures_dir / FIXTURE_FILE
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload.get("cases", [])
    return cases


def _override_only_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases if not c.get("bert_required", True)]


def _bert_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in cases if c.get("bert_required", True)]


class _StubAnalyzer(SentimentAnalyzer):
    """Stub used for override-only fixtures.

    Returns a known POZITIF/0.5 baseline so SLA/Tier-2 fallbacks have room to
    fire. Pre-BERT overrides (critical/tier1) short-circuit before this is
    ever called.
    """

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        return [AnalyzerPrediction(label="POZITIF", score=0.5) for _ in texts]


def _assert_case(result: Any, case: dict[str, Any]) -> None:
    expected_label = case.get("expected_label")
    if expected_label is not None:
        assert result.sentiment_label == expected_label, (
            f"[{case['id']}] label mismatch: got {result.sentiment_label!r}, "
            f"expected {expected_label!r}"
        )

    options = case.get("expected_label_options")
    if options is not None:
        assert result.sentiment_label in options, (
            f"[{case['id']}] label {result.sentiment_label!r} not in {options}"
        )

    if (es := case.get("expected_score")) is not None:
        assert abs(result.sentiment_score - es) < SCORE_TOLERANCE, (
            f"[{case['id']}] score {result.sentiment_score} != {es} ± {SCORE_TOLERANCE}"
        )

    if (lo := case.get("expected_score_min")) is not None:
        assert result.sentiment_score >= lo, (
            f"[{case['id']}] score {result.sentiment_score} < min {lo}"
        )
    if (hi := case.get("expected_score_max")) is not None:
        assert result.sentiment_score <= hi, (
            f"[{case['id']}] score {result.sentiment_score} > max {hi}"
        )

    if (layer := case.get("expected_layer")) is not None:
        layers = [o.layer for o in result.overrides_applied]
        assert layer in layers, (
            f"[{case['id']}] expected layer {layer!r} not in {layers!r}"
        )

    if (sub := case.get("expected_sla_substring")) is not None:
        assert result.sla_detected is not None, f"[{case['id']}] sla_detected missing"
        assert sub in result.sla_detected, (
            f"[{case['id']}] {sub!r} not in {result.sla_detected!r}"
        )

    if (cp := case.get("expected_customer_perspective")) is not None:
        assert result.customer_perspective == cp, (
            f"[{case['id']}] customer_perspective {result.customer_perspective!r} "
            f"!= {cp!r}"
        )

    if (cmp := case.get("expected_company_perspective")) is not None:
        assert result.company_perspective == cmp, (
            f"[{case['id']}] company_perspective {result.company_perspective!r} "
            f"!= {cmp!r}"
        )


def test_fixtures_file_exists(fixtures_dir: Path) -> None:
    """Ensure snapshot fixtures are present (file shipped with the package)."""
    assert (fixtures_dir / FIXTURE_FILE).exists(), (
        f"{FIXTURE_FILE} missing — see fixture _meta block for regeneration."
    )


def test_override_only_snapshot_cases(fixtures_dir: Path) -> None:
    cases = _override_only_cases(_load_cases(fixtures_dir))
    if not cases:
        pytest.skip("No override-only fixtures present")

    pipeline = AnalysisPipeline(analyzer=_StubAnalyzer())
    for case in cases:
        result = pipeline.analyze(case["text"])
        _assert_case(result, case)


@pytest.mark.slow
def test_bert_snapshot_cases(fixtures_dir: Path) -> None:
    """Run BERT-dependent fixtures against the real model.

    Skip with: `pytest -m "not slow"`. Run with: `pytest -m slow`.
    Set IMGA_RUN_SLOW=1 to force-enable when invoked without -m.
    """
    if not os.environ.get("IMGA_RUN_SLOW"):
        pytest.skip("BERT model load required; set IMGA_RUN_SLOW=1 or use -m slow")

    cases = _bert_cases(_load_cases(fixtures_dir))
    if not cases:
        pytest.skip("No BERT fixtures present")

    from imga_core import BertSentimentAnalyzer

    pipeline = AnalysisPipeline(analyzer=BertSentimentAnalyzer())
    for case in cases:
        result = pipeline.analyze(case["text"])
        _assert_case(result, case)
