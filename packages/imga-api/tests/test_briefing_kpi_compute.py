"""Sprint 8.3.11 R2 — server-side KPI compute + finish_reason guard.

Three test groups:

  * ``_compute_kpi_changes`` — previous=0 produces ``change_pct=None``
    + ``"yeni başlangıç"`` label; happy path produces the expected
    delta with the right ``direction`` value.
  * ``_check_finish_reason`` — MAX_TOKENS / SAFETY / RECITATION
    surface as the new error types BEFORE the parser sees a partial
    body.
  * Sentinel imports — the new error classes are reachable from
    ``imga_core.llm`` so the route layer can catch them by name.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from imga_core.llm import (
    LLMResponseBlockedError,
    LLMTokenLimitError,
)
from imga_core.llm.gemini import GeminiProvider

from imga_api.services.executive_briefing_service import (
    _compute_kpi_changes,
    _PeriodStats,
)


def _stats(**overrides: object) -> _PeriodStats:
    base: dict[str, object] = {
        "total_reviews": 0,
        "nps_score": None,
        "avg_sentiment": None,
        "negative_share": 0.0,
        "top_categories": [],
    }
    base.update(overrides)
    return _PeriodStats(**base)  # type: ignore[arg-type]


# --- _compute_kpi_changes ----------------------------------------------


def test_kpi_changes_previous_zero_emits_yeni_baslangic_label() -> None:
    """Regression: division by zero used to surface as ±Inf or NaN
    in the LLM output. Now: change_pct=None + change_label set."""
    current = _stats(total_reviews=9770)
    previous = _stats(total_reviews=0)
    rows = _compute_kpi_changes(current, previous)
    review = next(r for r in rows if r["metric"] == "Toplam Yorum")
    assert review["change_pct"] is None
    assert review["change_label"] == "yeni başlangıç"
    assert review["direction"] == "flat"
    assert review["current"] == 9770
    assert review["previous"] == 0


def test_kpi_changes_happy_path_produces_expected_delta() -> None:
    """Both periods populated → standard percentage with the
    correct ``direction`` derived from the sign."""
    current = _stats(total_reviews=120, negative_share=0.40)
    previous = _stats(total_reviews=100, negative_share=0.50)
    rows = _compute_kpi_changes(current, previous)
    review = next(r for r in rows if r["metric"] == "Toplam Yorum")
    assert review["change_pct"] == 20.0
    assert review["direction"] == "up"
    negshare = next(r for r in rows if r["metric"] == "Negatif Yorum Oranı")
    # 0.40 vs 0.50 → -20% drop.
    assert negshare["change_pct"] == -20.0
    assert negshare["direction"] == "down"


def test_kpi_changes_omits_metric_when_both_periods_missing() -> None:
    """Tenants without NPS-bearing rows have nps_score=None on both
    sides — that metric drops out so the briefing doesn't emit a
    "0 → 0" row."""
    current = _stats(total_reviews=10)
    previous = _stats(total_reviews=10)
    rows = _compute_kpi_changes(current, previous)
    metrics = {r["metric"] for r in rows}
    assert "NPS" not in metrics  # both nps_score values are None
    assert "Toplam Yorum" in metrics


# --- _check_finish_reason ---------------------------------------------


def _response_with_finish(name: str, text: str = "") -> SimpleNamespace:
    finish = SimpleNamespace(name=name)
    candidate = SimpleNamespace(finish_reason=finish)
    return SimpleNamespace(candidates=[candidate], text=text)


def test_finish_reason_stop_passes_through() -> None:
    """STOP is the happy path — no exception raised."""
    GeminiProvider._check_finish_reason(_response_with_finish("STOP"))
    GeminiProvider._check_finish_reason(_response_with_finish(""))


def test_finish_reason_max_tokens_raises_token_limit_error() -> None:
    """The Sprint 8.3.11 R1 markdown-fence parser fix masked this
    case in production. R2 surfaces it explicitly."""
    response = _response_with_finish("MAX_TOKENS", text='{"partial":')
    with pytest.raises(LLMTokenLimitError, match="token sınırına"):
        GeminiProvider._check_finish_reason(response)


def test_finish_reason_safety_raises_blocked_error() -> None:
    response = _response_with_finish("SAFETY")
    with pytest.raises(LLMResponseBlockedError, match="engellendi"):
        GeminiProvider._check_finish_reason(response)


def test_finish_reason_recitation_raises_blocked_error() -> None:
    """Recitation = the model regurgitated copyrighted content; the
    SDK blocks the response. Same UX as SAFETY."""
    response = _response_with_finish("RECITATION")
    with pytest.raises(LLMResponseBlockedError, match="engellendi"):
        GeminiProvider._check_finish_reason(response)


def test_finish_reason_other_falls_through_to_parser() -> None:
    """Unknown reasons (``OTHER`` or anything new) shouldn't crash —
    log + let the downstream parser try, since we don't know if the
    body is usable."""
    GeminiProvider._check_finish_reason(_response_with_finish("OTHER"))
