"""Sprint 9.4.4 — briefing service audit row on all-keys-exhausted.

The Sprint 9.4.3 B fix (rotator falls through on LLMProviderError)
worked, but production telemetry on 12.05.2026 12:07:13 caught a
follow-on bug: when every key 504'd in turn and the rotator finally
raised ``AllKeysExhaustedError``, NO row landed in
``llm_call_audit``. The auditor's ``__aexit__`` is supposed to
auto-record failures, but the empirical observation is that the
row was missing. The fix wraps the rotator call in an explicit
try/except that calls ``record_failure`` ahead of ``__aexit__`` so
the error fields are set with the right classification at the
call site.

This regression pins the contract: an all-keys-exhausted briefing
attempt MUST land exactly one audit row with ``success=False`` and
``error_type='all_keys_exhausted'``. If a future refactor drops
the explicit record_failure (or breaks the SAVEPOINT path that
inserts the row), the test fails here rather than the operator
discovering it from a missing dashboard chart.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from imga_core.llm.errors import AllKeysExhaustedError
from imga_core.llm.key_rotation import GeminiKey
from imga_db.models import LlmCallAudit, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.executive_briefing_service import (
    ExecutiveBriefingService,
)


@pytest.mark.asyncio
async def test_audit_row_lands_when_rotator_exhausts(
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
        "imga_api.services.executive_briefing_service.load_active_gemini_keys",
        _fake_load_keys,
    )

    # 2) Force the rotator to surface the all-keys-exhausted path. The
    #    real rotator catches LLMProviderError + walks every key; we
    #    short-circuit straight to the terminal raise so the test
    #    doesn't have to mock the provider's SDK shape.
    async def _fake_rotation(_self: object, _operation: object) -> None:
        raise AllKeysExhaustedError(
            "All LLM keys in rotation failed (RateLimit / InvalidKey / "
            "LLMProviderError)"
        )

    monkeypatch.setattr(
        "imga_core.llm.key_rotation.GeminiKeyRotator.call_with_rotation",
        _fake_rotation,
    )

    service = ExecutiveBriefingService(
        admin_session, tenant_id=tid, user_id=None,
    )
    today = datetime.now(UTC).date()
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        with pytest.raises(AllKeysExhaustedError):
            await service.generate(
                period="month",
                date_from=today - __import__("datetime").timedelta(days=30),
                date_to=today,
            )

    # Verify the audit row landed in a fresh transaction so any
    # SAVEPOINT machinery has settled. Empirically pre-fix the row
    # was missing here — the assertion is the load-bearing one.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(LlmCallAudit)
                .where(LlmCallAudit.tenant_id == tid)
                .where(LlmCallAudit.call_type == "briefing")
            )
        ).scalars().all()

    assert len(rows) == 1, (
        f"Exactly one audit row per failed briefing attempt; got "
        f"{len(rows)}. If zero, the SAVEPOINT insert rolled back with "
        "the parent transaction (deeper fix needed); if more, the "
        "instrumentation is double-firing."
    )
    audit = rows[0]
    assert audit.success is False
    assert audit.error_type == "all_keys_exhausted"
    assert audit.error_message and "rotation failed" in audit.error_message.lower()
    assert audit.model_provider == "gemini"
    assert audit.call_type == "briefing"
