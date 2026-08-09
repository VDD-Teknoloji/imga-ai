"""Sprint 9.4.4 / 9.4.5 — briefing service audit row on all-keys-exhausted.

Sprint 9.4.3 B (rotator falls through on LLMProviderError) shipped,
and prod telemetry 12.05.2026 12:07:13 + 13:30 caught a follow-on:
the audit row was missing on the all-keys-exhausted path because
the auditor's SAVEPOINT INSERT was parasitic on the parent
transaction — when the /tenants/me/executive-briefings/generate
route propagated the service exception OUT of its
``async with app_session.begin():`` block, the parent rolled back
and took the SAVEPOINT row with it. /admin/llm-audit then had no
record of the most operationally interesting failure paths.

Sprint 9.4.5 applies the deferred-raise pattern to the /generate
route: LLM-class exceptions are caught INSIDE the begin() block,
stashed in ``deferred_exc``, and re-raised AFTER the block exits
cleanly (commit). /run-now already had this shape implicitly.
The auditor's SAVEPOINT row commits with the parent, surviving
the operator-facing failure.

Two contracts pinned here:

  * **Direct-service test** (Sprint 9.4.4) — when a test wraps
    ``service.generate(...)`` in ``async with begin() / pytest.raises``,
    the begin() block exits cleanly (pytest.raises catches before
    propagation) and the audit row commits. This pins the auditor
    + service contract end to end.
  * **Through-route test** (Sprint 9.4.5) — when an actual HTTP
    POST hits ``/tenants/me/executive-briefings/generate`` and the
    rotator exhausts, the route's deferred-raise pattern must
    preserve the audit row. This is the prod-shape regression.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core.llm.errors import AllKeysExhaustedError
from imga_core.llm.key_rotation import GeminiKey
from imga_db.models import LlmCallAudit, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.executive_briefing_service import (
    ExecutiveBriefingService,
)
from imga_api.services.llm_credentials import LlmKeySelection
from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_audit_row_lands_when_rotator_exhausts(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, tid, _pw = semi_auto_tenant

    # 1) Bypass the DB credentials load — return one fake key so the
    #    service constructs a rotator without hitting tenant_llm_credentials.
    async def _fake_load_keys(
        _session: object, _tid: UUID
    ) -> LlmKeySelection:
        return LlmKeySelection(
            provider="gemini",
            model=None,
            keys=[
                GeminiKey(
                    id="fake-id", value="fake-value", label="fake", priority=0
                ),
            ],
        )

    monkeypatch.setattr(
        "imga_api.services.executive_briefing_service.load_active_llm_keys",
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


@pytest.mark.asyncio
async def test_generate_route_audit_survives_503_response(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 9.4.5 — drive ``/tenants/me/executive-briefings/generate``
    through TestClient, force the rotator to exhaust, and verify the
    audit row landed in the DB. Pre-9.4.5 this exact path lost the
    row because the route's try/except was OUTSIDE the
    ``async with begin()`` block, propagating the service exception
    out of the transaction and rolling the SAVEPOINT row back."""
    user, tid, pw = semi_auto_tenant

    async def _fake_load_keys(
        _session: object, _tid: UUID
    ) -> LlmKeySelection:
        return LlmKeySelection(
            provider="gemini",
            model=None,
            keys=[GeminiKey(id="fid", value="fval", label="fake", priority=0)],
        )

    async def _fake_rotation(_self: object, _operation: object) -> None:
        raise AllKeysExhaustedError(
            "All LLM keys in rotation failed (route-level test)"
        )

    monkeypatch.setattr(
        "imga_api.services.executive_briefing_service.load_active_llm_keys",
        _fake_load_keys,
    )
    monkeypatch.setattr(
        "imga_core.llm.key_rotation.GeminiKeyRotator.call_with_rotation",
        _fake_rotation,
    )

    token = login_token(batch_client, user.email, pw, tid)
    today = datetime.now(UTC).date()
    r = batch_client.post(
        "/tenants/me/executive-briefings/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "period": "month",
            "date_from": (today - __import__("datetime").timedelta(days=30))
            .isoformat(),
            "date_to": today.isoformat(),
            "force_refresh": True,
        },
    )
    # The route surfaces the all-keys-exhausted error to the operator.
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["detail"] == "all_keys_exhausted"

    # And — the load-bearing assertion — the audit row landed in the
    # DB even though the route raised. Pre-9.4.5 the parent
    # transaction rolled back and the SAVEPOINT row went with it.
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
        f"Route-level audit row missing (got {len(rows)}). The "
        "deferred-raise pattern in /generate must commit the parent "
        "transaction before re-raising the HTTPException."
    )
    audit = rows[0]
    assert audit.success is False
    assert audit.error_type == "all_keys_exhausted"
