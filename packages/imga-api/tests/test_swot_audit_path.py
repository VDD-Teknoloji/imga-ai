"""Sprint 9.5.6 — SWOT service audit row regression.

Pre-9.5.6 the llm_call_audit table never carried SWOT rows: the
auditor was wired into briefing + /analyze + batch chunks but
swot_service / okr_service had no LLMCallAuditor wrap at all. The
gemini-3-flash-preview cutover (Sprint 9.5.4) hit 6/6 504s on SWOT
payloads in production (req=bf7ee228, 2026-05-13 08:18-08:19), and
the operator had zero visibility on /admin/llm-audit because the
service never wrote a row in the first place.

This module pins the contract added in 9.5.6:

  * SWOT generation lands exactly ONE llm_call_audit row per call
    (success or failure path).
  * On AllKeysExhaustedError (the 504-storm shape) the row has
    success=False, error_type='all_keys_exhausted', error_message
    populated.
  * The row carries the right call_type ('strategic_report') so
    /admin/llm-audit's filter shows SWOT under the strategic-report
    bucket rather than collapsing it under 'classification'.

The test bypasses the real DB credential load + the real rotator
so it doesn't need a live Gemini key; the only thing under test is
the auditor wrap inside swot_service.generate().
"""

from __future__ import annotations

from uuid import UUID

import pytest
from imga_core.llm.errors import AllKeysExhaustedError
from imga_core.llm.key_rotation import GeminiKey
from imga_db.models import LlmCallAudit, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.swot_service import SwotService


@pytest.mark.asyncio
async def test_swot_audit_row_lands_when_rotator_exhausts(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, tid, _pw = semi_auto_tenant

    # 1) Bypass the DB credentials load — return one fake key so the
    #    service constructs a rotator without hitting tenant_llm_credentials.
    async def _fake_load_keys(_session: object, _tid: UUID) -> list[GeminiKey]:
        return [
            GeminiKey(id="fake-id", value="fake-value", label="fake", priority=0),
        ]

    monkeypatch.setattr(
        "imga_api.services.swot_service.load_active_gemini_keys",
        _fake_load_keys,
    )

    # 2) Force the rotator to surface the all-keys-exhausted path.
    async def _fake_rotation(_self: object, _operation: object) -> None:
        raise AllKeysExhaustedError(
            "All LLM keys in rotation failed (504 DEADLINE_EXCEEDED storm)"
        )

    monkeypatch.setattr(
        "imga_core.llm.key_rotation.GeminiKeyRotator.call_with_rotation",
        _fake_rotation,
    )

    service = SwotService(admin_session, tenant_id=tid, user_id=None)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        with pytest.raises(AllKeysExhaustedError):
            await service.generate()

    # Verify the audit row landed in a fresh transaction so any
    # SAVEPOINT machinery has settled.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(LlmCallAudit)
                .where(LlmCallAudit.tenant_id == tid)
                .where(LlmCallAudit.call_type == "strategic_report")
            )
        ).scalars().all()

    assert len(rows) == 1, (
        f"Exactly one audit row per failed SWOT attempt; got "
        f"{len(rows)}. If zero, swot_service forgot the LLMCallAuditor "
        "wrap (the bug Sprint 9.5.6 fixed) OR the SAVEPOINT row rolled "
        "back with the parent transaction; if more, the instrumentation "
        "is double-firing."
    )
    audit = rows[0]
    assert audit.success is False
    assert audit.error_type == "all_keys_exhausted"
    assert audit.error_message and "rotation" in audit.error_message.lower()
    assert audit.model_provider == "gemini"
    assert audit.call_type == "strategic_report"
    assert audit.prompt_template_key == "swot"
    assert audit.prompt_hash and len(audit.prompt_hash) == 64
