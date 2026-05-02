"""POST /tenants/me/reviews/{id}/create-ticket coverage.

Manual review-to-ticket promotion. Covers the four state transitions
the route exposes:

  1. Skipped review (decision=SKIPPED_THRESHOLD) → 201 + ticket
  2. Already-ticketed review → 409 (idempotency / no double-mint)
  3. Viewer role → 403
  4. Cross-tenant review_id → 404 (RLS hides it)
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    AutomationMode,
    Review,
    ReviewDecision,
    Ticket,
    TicketState,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services import AuditService, UserService
from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)


async def _seed_skipped_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str = "kargom kötü bir deneyim oldu",
) -> Review:
    """Insert a skipped review (no ticket linked) directly so the test
    doesn't depend on the analyze flow working end-to-end."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        review = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label="NEGATIF",
            sentiment_score=-0.6,
            primary_category="kargo",
            primary_confidence=0.55,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason="confidence_under_threshold",
            ticket_id=None,
            submitted_by_user_id=None,
            analyzed_at=datetime.now(UTC),
        )
        admin_session.add(review)
        await admin_session.flush()
        admin_session.expunge(review)
    return review


@pytest.mark.asyncio
async def test_skipped_review_can_be_manually_promoted(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    review = await _seed_skipped_review(admin_session, tenant_id=tid)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        f"/tenants/me/reviews/{review.id}/create-ticket",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["review_id"] == str(review.id)
    assert body["ticket_state"] == TicketState.OPEN.value
    new_ticket_id = UUID(body["ticket_id"])

    # Review row updated, ticket exists.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        refreshed_review = (
            await admin_session.execute(
                select(Review).where(Review.id == review.id)
            )
        ).scalar_one()
        ticket = (
            await admin_session.execute(
                select(Ticket).where(Ticket.id == new_ticket_id)
            )
        ).scalar_one()
    assert refreshed_review.ticket_id == new_ticket_id
    assert refreshed_review.decision_reason == "manually_promoted_to_ticket"
    # Original decision is preserved as audit trail (not overwritten).
    assert refreshed_review.decision == ReviewDecision.SKIPPED_THRESHOLD
    # Ticket attributed to the analyst, not system (created_by_user_id != None).
    assert ticket.created_by_user_id == user.id
    assert ticket.review_id == review.id


@pytest.mark.asyncio
async def test_already_ticketed_review_returns_409(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Second promotion attempt against the same review must conflict —
    no double-mint."""
    user, tid, pw = semi_auto_tenant
    review = await _seed_skipped_review(admin_session, tenant_id=tid)

    token = login_token(batch_client, user.email, pw, tid)
    first = batch_client.post(
        f"/tenants/me/reviews/{review.id}/create-ticket",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    second = batch_client.post(
        f"/tenants/me/reviews/{review.id}/create-ticket",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_viewer_cannot_promote_review(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Viewer role is read-only by contract; the route's role guard
    must reject it before the service runs."""
    _admin, tid, _pw = semi_auto_tenant
    review = await _seed_skipped_review(admin_session, tenant_id=tid)

    # Seed a viewer in the same tenant via UserService (real argon2 hash).
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    viewer_pw = "Viewer-Pass-123!"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=f"viewer-{uuid4().hex[:6]}@example.com",
            password=viewer_pw,
            full_name="Viewer User",
        )
        await usvc.attach_to_tenant(
            user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER
        )
        viewer_id = viewer.id
        viewer_email = viewer.email

    try:
        token = login_token(batch_client, viewer_email, viewer_pw, tid)
        r = batch_client.post(
            f"/tenants/me/reviews/{review.id}/create-ticket",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": str(viewer_id)}
            )


@pytest.mark.asyncio
async def test_cross_tenant_review_id_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenant A seeds a review; tenant B's promotion attempt must 404."""
    _user_a, tid_a, _pw_a = semi_auto_tenant
    review = await _seed_skipped_review(admin_session, tenant_id=tid_a)

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session,
        automation_mode=AutomationMode.SEMI_AUTO,
        name_prefix="Cross-Tenant Co",
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.post(
            f"/tenants/me/reviews/{review.id}/create-ticket",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404, r.text
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)
