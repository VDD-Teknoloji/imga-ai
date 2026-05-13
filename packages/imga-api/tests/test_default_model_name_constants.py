"""Sprint 9.5.4 — service-level DEFAULT_MODEL_NAME pinning.

The three strategy services (executive_briefing, OKR, SWOT) each
carry a ``DEFAULT_MODEL_NAME`` literal that feeds:

  * the persisted ``model_name`` column on strategic_reports +
    executive_briefings,
  * the ``LLMCallContext.model_name`` on llm_call_audit rows,
  * the seed argument used by ``_build_provider_without_key``.

Model-cutover history:

  * Sprint 9.5 A3 (commit 26658c2): cut the wire-level Gemini default
    to gemini-2.5-pro by flipping kwarg defaults in
    imga_core.llm.gemini. Service-level constants stayed on flash;
    audit lied. The audit-log lie persisted until 9.5.1 caught it.

  * Sprint 9.5.1 A3.1 (commit 22f20fb): synced these three constants
    to "gemini-2.5-pro". Wire + audit + persistence finally agreed.

  * Sprint 9.5.2: production hit 6/6 504 DEADLINE_EXCEEDED on
    briefing payloads under gemini-2.5-pro. Server-agent logs
    showed 2.5-flash also ~22% 504 on the same payload — the 2.5
    family doesn't fit briefing inside Google's 30s infra SLA.
    Fell back to "gemini-2.0-flash".

  * Sprint 9.5.4 (this commit): 2.0-flash returned 404 NOT_FOUND
    ("no longer available to new users") — Google has closed 2.0
    to new accounts and is sunsetting it entirely 2026-06-01.
    Switched to "gemini-3-flash-preview" — different compute pool
    with (hypothetically) a more forgiving SLA pattern for
    briefing-sized payloads.

If 3-flash-preview also 504s, Sprint 9.5.5 swaps to
gemini-3.1-flash-lite. If it 404s, the model-name string needs
re-verification (the "-preview" suffix is moving-target territory).

When the next cutover happens, update the expected literal here
alongside the const flip so the pin stays honest. If we ever want
a per-call-type override (e.g. flash-lite for OKR, full preview
for briefing), delete the cross-check assertion deliberately, not
by accident.
"""

from __future__ import annotations

from imga_api.services.executive_briefing_service import (
    DEFAULT_MODEL_NAME as BRIEFING_MODEL,
)
from imga_api.services.okr_service import DEFAULT_MODEL_NAME as OKR_MODEL
from imga_api.services.swot_service import DEFAULT_MODEL_NAME as SWOT_MODEL

_EXPECTED = "gemini-3-flash-preview"


def test_briefing_default_model_is_gemini_3_flash_preview() -> None:
    assert BRIEFING_MODEL == _EXPECTED, (
        f"executive_briefing_service.DEFAULT_MODEL_NAME = {BRIEFING_MODEL!r}; "
        f"Sprint 9.5.4 pins it to {_EXPECTED!r} (2.5 family 504s, "
        "2.0-flash 404 deprecated)."
    )


def test_okr_default_model_is_gemini_3_flash_preview() -> None:
    assert OKR_MODEL == _EXPECTED, (
        f"okr_service.DEFAULT_MODEL_NAME = {OKR_MODEL!r}; "
        f"Sprint 9.5.4 pins it to {_EXPECTED!r}."
    )


def test_swot_default_model_is_gemini_3_flash_preview() -> None:
    assert SWOT_MODEL == _EXPECTED, (
        f"swot_service.DEFAULT_MODEL_NAME = {SWOT_MODEL!r}; "
        f"Sprint 9.5.4 pins it to {_EXPECTED!r}."
    )


def test_all_three_strategy_constants_agree() -> None:
    """Cross-check — the three strategy services should be on the same
    model for now. If we want to fork them later (e.g. flash-lite for
    OKR + preview for briefing) we delete this assertion deliberately,
    not by accident."""
    assert BRIEFING_MODEL == OKR_MODEL == SWOT_MODEL, (
        f"strategy services diverged: briefing={BRIEFING_MODEL!r} "
        f"okr={OKR_MODEL!r} swot={SWOT_MODEL!r}"
    )
