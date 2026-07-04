"""Sprint 9.4.3 A — /tenants/me/analyze audit integration regression.

Pre-9.4.3 the only call site instrumented with ``LLMCallAuditor``
was the executive briefing generator. Every other LLM-touching
path (single-review analyze, batch chunks, SWOT, OKR, decision
audit) wrote zero rows to ``llm_call_audit``, leaving
/admin/llm-audit covering only ~5% of the platform's actual LLM
traffic. Demo's "AI karar izlenebilirliği" narrative was broken.

This sprint wires the auditor at the single-review and batch-chunk
boundaries. These tests pin that:

  * A successful /tenants/me/analyze lands exactly one
    ``llm_call_audit`` row with ``call_type='classification'`` and
    a non-null prompt_hash anchored to the request text.
  * ``fallback_used`` reflects whether the LLM actually contributed
    to the decision: when the stub pipeline produces a result
    WITHOUT ``categorization.llm_result``, the keyword fallback
    owned the call and ``fallback_used`` flips to True.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import LlmCallAudit, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_analyze_writes_one_audit_row_per_request(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Single /analyze call.
    r = batch_client.post(
        "/tenants/me/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Kargom gelmedi, çok kötü hizmet"},
    )
    assert r.status_code == 200, r.text

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(LlmCallAudit)
                .where(LlmCallAudit.tenant_id == tid)
                .where(LlmCallAudit.call_type == "classification")
            )
        ).scalars().all()

    assert len(rows) == 1, (
        f"Exactly one audit row per /analyze request; got {len(rows)} — "
        "if zero, the auditor isn't wired; if more, the instrumentation "
        "is double-firing somewhere up the call tree."
    )
    audit = rows[0]
    assert audit.call_type == "classification"
    assert audit.success is True
    assert audit.model_provider == "gemini"
    assert audit.prompt_hash, "prompt_hash must be a non-empty SHA256 digest"
    assert len(audit.prompt_hash) == 64
    # The conftest stub pipeline doesn't consult an LLM — the keyword
    # classifier owns the decision — so the auditor should record
    # fallback_used=True. This also pins the fallback signal so a
    # future stub change that DOES wire an LLM result flips this
    # assertion on the same test (catches "we forgot to update the
    # stub" regressions).
    assert audit.fallback_used is True


@pytest.mark.asyncio
async def test_analyze_audit_row_carries_actor_user_id(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """The audit row's ``actor_user_id`` must point at the caller —
    /admin/decision-audit cross-references this column to attribute
    LLM activity to a specific operator."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "bir başka analiz"},
    )
    assert r.status_code == 200

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        audit = (
            await admin_session.execute(
                select(LlmCallAudit).where(LlmCallAudit.tenant_id == tid)
            )
        ).scalar_one()
    assert audit.actor_user_id == user.id


@pytest.mark.asyncio
async def test_viewer_cannot_analyze(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 13 rol matrisi: /tenants/me/analyze reviews'a satır yazar
    ve auto-ticket açabilir — VIEWER (salt-okuma) 403 almalı."""
    from uuid import uuid4

    from imga_db.models import UserTenantRole

    from imga_api.services import AuditService, UserService

    _admin, tid, _pw = semi_auto_tenant

    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    viewer_plain = "Viewer-Password-123!"
    viewer_email = f"viewer-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=viewer_email, password=viewer_plain, full_name="Rev Viewer"
        )
        await usvc.attach_to_tenant(
            user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER
        )
        viewer_id = viewer.id

    try:
        token = login_token(batch_client, viewer_email, viewer_plain, tid)
        r = batch_client.post(
            "/tenants/me/analyze",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "Kargom gelmedi çok kötü bir deneyim"},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(viewer_id)},
            )
