"""Sprint 9.5.1 A3.1 — service-level DEFAULT_MODEL_NAME pinning.

Sprint 9.5 A3 (commit 26658c2) cut the wire-level Gemini default
over to gemini-2.5-pro for SWOT / OKR / executive-briefing
generation by flipping kwarg defaults in imga_core.llm.gemini. The
wire-level call IS hitting pro since the 9.5 deploy.

But each of the three service modules carries its OWN
``DEFAULT_MODEL_NAME`` literal that feeds:

  * the persisted ``model_name`` column on strategic_reports +
    executive_briefings,
  * the ``LLMCallContext.model_name`` on llm_call_audit rows,
  * the seed argument used by ``_build_provider_without_key``.

Pre-9.5.1 those three constants still said "gemini-2.5-flash"; the
audit log + persistence tables lied while the real SDK call was
pro. The 12.05.2026 production smoke caught the divergence in the
``llm_call_audit`` table.

This module pins the post-9.5.1 values as a regression guard. If a
future commit flips any of them back to flash (e.g. an ill-judged
revert of the A3 series), this fails immediately with a clear
"don't break the cutover" signal — much better than the audit-log
hunt the user had to do to find the bug.

If we ever want a per-call-type override (e.g. briefing on pro,
OKR on flash for cost reasons), this test is the gate. Adjust the
expected value alongside the const flip so the pin stays honest.
"""

from __future__ import annotations

from imga_api.services.executive_briefing_service import (
    DEFAULT_MODEL_NAME as BRIEFING_MODEL,
)
from imga_api.services.okr_service import DEFAULT_MODEL_NAME as OKR_MODEL
from imga_api.services.swot_service import DEFAULT_MODEL_NAME as SWOT_MODEL


def test_briefing_default_model_is_pro() -> None:
    assert BRIEFING_MODEL == "gemini-2.5-pro", (
        f"executive_briefing_service.DEFAULT_MODEL_NAME = {BRIEFING_MODEL!r}; "
        "Sprint 9.5.1 A3.1 pins it to gemini-2.5-pro so audit + "
        "executive_briefings.model_name reflect the wire-level call."
    )


def test_okr_default_model_is_pro() -> None:
    assert OKR_MODEL == "gemini-2.5-pro", (
        f"okr_service.DEFAULT_MODEL_NAME = {OKR_MODEL!r}; "
        "Sprint 9.5.1 A3.1 pins it to gemini-2.5-pro."
    )


def test_swot_default_model_is_pro() -> None:
    assert SWOT_MODEL == "gemini-2.5-pro", (
        f"swot_service.DEFAULT_MODEL_NAME = {SWOT_MODEL!r}; "
        "Sprint 9.5.1 A3.1 pins it to gemini-2.5-pro. The pre-9.5.1 "
        "comment about free-tier 429s is no longer load-bearing — "
        "production tenants are on paid Tier 1 quota."
    )


def test_all_three_strategy_constants_agree() -> None:
    """Cross-check — the three strategy services should be on the same
    model for now. If we want to fork them later (e.g. flash for OKR
    to cut cost on lower-stakes prompts) we delete this assertion
    deliberately, not by accident."""
    assert BRIEFING_MODEL == OKR_MODEL == SWOT_MODEL, (
        f"strategy services diverged: briefing={BRIEFING_MODEL!r} "
        f"okr={OKR_MODEL!r} swot={SWOT_MODEL!r}"
    )
