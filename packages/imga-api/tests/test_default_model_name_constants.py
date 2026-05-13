"""Sprint 9.5.2 — service-level DEFAULT_MODEL_NAME pinning.

The three strategy services (executive_briefing, OKR, SWOT) each
carry a ``DEFAULT_MODEL_NAME`` literal that feeds:

  * the persisted ``model_name`` column on strategic_reports +
    executive_briefings,
  * the ``LLMCallContext.model_name`` on llm_call_audit rows,
  * the seed argument used by ``_build_provider_without_key``.

Origin story:

  * Sprint 9.5 A3 (commit 26658c2) cut the wire-level Gemini default
    to gemini-2.5-pro by flipping kwarg defaults in
    imga_core.llm.gemini. But these service-level constants stayed
    on "gemini-2.5-flash" — wire was pro, audit said flash. The
    audit-log lie persisted until 9.5.1 caught it.

  * Sprint 9.5.1 A3.1 (commit 22f20fb) flipped these three constants
    to "gemini-2.5-pro" so audit + persistence finally agreed with
    the wire-level call.

  * Sprint 9.5.2 (this commit) emergency-falls-back to
    "gemini-2.0-flash". Production smoke 2026-05-12 showed pro
    returning 6/6 504 DEADLINE_EXCEEDED on briefing payloads, and
    server-agent logs flagged 2.5-flash at ~22% 504 on the same
    payload — the 2.5 family doesn't fit briefing's payload size
    inside Google's 30s infra SLA. 2.0-flash has 2K RPM / 4M TPM /
    unlimited RPD on Tier 1 paid (vs Pro's 150 / 2M / 1K), and
    isn't showing the 504 pattern.

If 2.0-flash ALSO degrades, Sprint 9.6 lands a payload-shape
refactor (sample-then-summarise OR map/reduce) and these constants
move again. When that happens, update the expected literal here
alongside the const flip so the pin stays honest.

If we ever want a per-call-type override (e.g. briefing on pro,
OKR on flash for cost reasons), delete the cross-check assertion
deliberately, not by accident.
"""

from __future__ import annotations

from imga_api.services.executive_briefing_service import (
    DEFAULT_MODEL_NAME as BRIEFING_MODEL,
)
from imga_api.services.okr_service import DEFAULT_MODEL_NAME as OKR_MODEL
from imga_api.services.swot_service import DEFAULT_MODEL_NAME as SWOT_MODEL

_EXPECTED = "gemini-2.0-flash"


def test_briefing_default_model_is_2_0_flash() -> None:
    assert BRIEFING_MODEL == _EXPECTED, (
        f"executive_briefing_service.DEFAULT_MODEL_NAME = {BRIEFING_MODEL!r}; "
        f"Sprint 9.5.2 pins it to {_EXPECTED!r} (2.5 family caused "
        "504 DEADLINE_EXCEEDED on briefing payloads in prod)."
    )


def test_okr_default_model_is_2_0_flash() -> None:
    assert OKR_MODEL == _EXPECTED, (
        f"okr_service.DEFAULT_MODEL_NAME = {OKR_MODEL!r}; "
        f"Sprint 9.5.2 pins it to {_EXPECTED!r}."
    )


def test_swot_default_model_is_2_0_flash() -> None:
    assert SWOT_MODEL == _EXPECTED, (
        f"swot_service.DEFAULT_MODEL_NAME = {SWOT_MODEL!r}; "
        f"Sprint 9.5.2 pins it to {_EXPECTED!r}."
    )


def test_all_three_strategy_constants_agree() -> None:
    """Cross-check — the three strategy services should be on the same
    model for now. If we want to fork them later (e.g. flash-2.0 for
    OKR + pro for briefing) we delete this assertion deliberately,
    not by accident."""
    assert BRIEFING_MODEL == OKR_MODEL == SWOT_MODEL, (
        f"strategy services diverged: briefing={BRIEFING_MODEL!r} "
        f"okr={OKR_MODEL!r} swot={SWOT_MODEL!r}"
    )
