"""Kategori bazlı ticket yönlendirme + e-posta outbox kapsamı.

Beş blok:

  1. Kural CRUD — create 201, duplicate 409, viewer-write 403,
     patch/delete (soft) davranışı.
  2. Otomatik ticket açılışında yönlendirme — semi_auto tenant + aktif
     kural + negatif analiz → assignee atanır + 'ticket_opened' outbox
     satırı yazılır (record_and_decide service-layer, deterministik
     el yapımı AnalysisResult ile).
  3. 'belirsiz' promote — migration 0036'nın global belirsiz satırı
     sayesinde artık 201 (HATA-03 regresyonu).
  4. sla_breach_tick — eşiği aşmış OPEN ticket'a TEK 'sla_breach'
     satırı; tick iki kez koşunca ikinci satır yazılmaz.
  5. email_outbox_tick — SMTP yapılandırılmamışken pending bırakır;
     monkeypatch'li sahte SMTP ile 'sent' + sent_at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from cachetools import TTLCache
from fastapi.testclient import TestClient
from imga_core import AnalysisResult, CategoryClassification, review_text_hash
from imga_db import create_engine, create_session_factory, set_current_tenant
from imga_db.models import (
    EmailOutbox,
    EmailOutboxEventType,
    EmailOutboxStatus,
    Review,
    ReviewDecision,
    Ticket,
    TicketRoutingRule,
    TicketState,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services import (
    AuditService,
    ReviewService,
    TenantConfigService,
    TicketService,
    UserService,
    email_sender,
)
from imga_api.workers.email_outbox_worker import (
    email_outbox_tick,
    sla_breach_tick,
)
from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)

# --- helpers ----------------------------------------------------------


def _headers(client: TestClient, user: User, pw: str, tid: UUID) -> dict[str, str]:
    token = login_token(client, user.email, pw, tid)
    return {"Authorization": f"Bearer {token}"}


async def _bind(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )


async def _seed_rule(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    category_code: str = "kargo",
    notify_email: str = "ops@example.com",
    assignee_user_id: UUID | None = None,
    sla_hours: int | None = None,
) -> UUID:
    async with admin_session.begin():
        await _bind(admin_session, tenant_id)
        rule = TicketRoutingRule(
            tenant_id=tenant_id,
            category_code=category_code,
            notify_email=notify_email,
            assignee_user_id=assignee_user_id,
            sla_hours=sla_hours,
        )
        admin_session.add(rule)
        await admin_session.flush()
        rule_id = rule.id
    return rule_id


async def _global_category_id(
    admin_session: AsyncSession, code: str
) -> UUID:
    async with admin_session.begin():
        row = (
            await admin_session.execute(
                text(
                    "SELECT id FROM categories "
                    "WHERE tenant_id IS NULL AND code = :c"
                ),
                {"c": code},
            )
        ).scalar_one()
    return UUID(str(row))


def _negative_analysis(text_value: str) -> AnalysisResult:
    """Deterministik NEGATIF + yüksek güvenli 'kargo' sınıflandırması —
    semi_auto eşiğini (confidence > 0.7, sentiment < -0.5) garantiler."""
    return AnalysisResult(
        text=text_value,
        sentiment_label="NEGATIF",
        sentiment_score=-0.85,
        categorization=CategoryClassification(
            primary="kargo", primary_confidence=0.9
        ),
    )


def _worker_ctx(factory: Any) -> dict[str, Any]:
    return {"worker_context": SimpleNamespace(admin_session_factory=factory)}


# --- 1. kural CRUD ----------------------------------------------------


@pytest.mark.asyncio
async def test_routing_rule_crud_flow(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    headers = _headers(batch_client, user, pw, tid)

    created = batch_client.post(
        "/tenants/me/ticket-routing",
        headers=headers,
        json={
            "category_code": "kargo",
            "notify_email": "kargo-ops@example.com",
            "sla_hours": 24,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    rule_id = body["id"]
    assert body["category_code"] == "kargo"
    assert body["notify_email"] == "kargo-ops@example.com"
    assert body["sla_hours"] == 24
    assert body["is_active"] is True

    # Aynı kategoriye ikinci kural — UNIQUE(tenant_id, category_code).
    dup = batch_client.post(
        "/tenants/me/ticket-routing",
        headers=headers,
        json={
            "category_code": "kargo",
            "notify_email": "baska@example.com",
        },
    )
    assert dup.status_code == 409, dup.text

    listed = batch_client.get(
        "/tenants/me/ticket-routing", headers=headers
    ).json()
    assert [r["id"] for r in listed["rules"]] == [rule_id]

    patched = batch_client.patch(
        f"/tenants/me/ticket-routing/{rule_id}",
        headers=headers,
        json={"notify_email": "yeni-ops@example.com", "sla_hours": 48},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["notify_email"] == "yeni-ops@example.com"
    assert patched.json()["sla_hours"] == 48

    deleted = batch_client.delete(
        f"/tenants/me/ticket-routing/{rule_id}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["is_active"] is False

    # Soft delete: default liste boş, include_inactive ile görünür.
    assert (
        batch_client.get(
            "/tenants/me/ticket-routing", headers=headers
        ).json()["rules"]
        == []
    )
    inactive = batch_client.get(
        "/tenants/me/ticket-routing?include_inactive=true",
        headers=headers,
    ).json()["rules"]
    assert [r["id"] for r in inactive] == [rule_id]


@pytest.mark.asyncio
async def test_viewer_cannot_write_routing_rules(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _admin, tid, _pw = semi_auto_tenant
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
        headers = {"Authorization": f"Bearer {token}"}
        r = batch_client.post(
            "/tenants/me/ticket-routing",
            headers=headers,
            json={
                "category_code": "kargo",
                "notify_email": "ops@example.com",
            },
        )
        assert r.status_code == 403, r.text
        # Okuma her role açık.
        assert (
            batch_client.get(
                "/tenants/me/ticket-routing", headers=headers
            ).status_code
            == 200
        )
        # Outbox penceresi yalnız tenant_admin.
        assert (
            batch_client.get(
                "/tenants/me/ticket-routing/outbox", headers=headers
            ).status_code
            == 403
        )
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(viewer_id)},
            )


# --- 2. otomatik ticket açılışında atama + outbox ----------------------


@pytest.mark.asyncio
async def test_auto_created_ticket_gets_assignee_and_outbox_row(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """semi_auto tenant + aktif kural + negatif analiz → bridge CREATE
    dalı kuralı uygular: assignee atanır ve 'ticket_opened' outbox
    satırı enqueue edilir. batch_client yalnız env/DB kablolaması için
    fixture zincirinde — akış service-layer sürülür ki eşik değerleri
    deterministik kalsın."""
    user, tid, _pw = semi_auto_tenant
    await _seed_rule(
        admin_session,
        tenant_id=tid,
        category_code="kargo",
        notify_email="kargo-ops@example.com",
        assignee_user_id=user.id,
    )

    text_value = f"Kargom kötü geldi {uuid4().hex[:8]}"
    cache: TTLCache[UUID, dict[str, object]] = TTLCache(maxsize=10, ttl=300)
    app_engine = create_engine("app")
    app_factory = create_session_factory(app_engine)
    try:
        async with app_factory() as app_session:
            audit = AuditService(app_session)
            tickets = TicketService(app_session, audit)
            config = TenantConfigService(app_session, audit, cache)
            reviews = ReviewService(app_session, audit, tickets, config)
            async with app_session.begin():
                await set_current_tenant(app_session, tid)
                result = await reviews.record_and_decide(
                    tenant_id=tid,
                    text=text_value,
                    analysis=_negative_analysis(text_value),
                    actor_user_id=None,
                )
                assert result.decision == ReviewDecision.CREATE
                assert result.ticket_id is not None
                ticket_id = result.ticket_id
    finally:
        await app_engine.dispose()

    async with admin_session.begin():
        await _bind(admin_session, tid)
        ticket = (
            await admin_session.execute(
                select(Ticket).where(Ticket.id == ticket_id)
            )
        ).scalar_one()
        outbox = (
            await admin_session.execute(
                select(EmailOutbox).where(
                    EmailOutbox.related_ticket_id == ticket_id
                )
            )
        ).scalars().all()
    assert ticket.assigned_to_user_id == user.id
    assert len(outbox) == 1
    row = outbox[0]
    assert row.event_type == EmailOutboxEventType.TICKET_OPENED
    assert row.status == EmailOutboxStatus.PENDING
    assert row.to_email == "kargo-ops@example.com"
    assert "Yeni Ticket" in row.subject
    assert f"/tickets/{ticket_id}" in row.body_text


# --- 3. 'belirsiz' promote artık 201 -----------------------------------


@pytest.mark.asyncio
async def test_belirsiz_review_can_be_promoted(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Migration 0036 global 'belirsiz' satırını ekledi — HATA-03'te
    409'a düşen promote artık 201 dönmeli."""
    user, tid, pw = semi_auto_tenant
    text_value = "ne olduğu belli olmayan bir yorum"
    async with admin_session.begin():
        await _bind(admin_session, tid)
        review = Review(
            tenant_id=tid,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label="NÖTR",
            sentiment_score=0.0,
            primary_category="belirsiz",
            primary_confidence=0.2,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_BELIRSIZ,
            decision_reason="primary_category_belirsiz",
            ticket_id=None,
            submitted_by_user_id=None,
            analyzed_at=datetime.now(UTC),
        )
        admin_session.add(review)
        await admin_session.flush()
        review_id = review.id

    headers = _headers(batch_client, user, pw, tid)
    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/create-ticket",
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["ticket_id"] is not None


# --- 4. sla_breach_tick -------------------------------------------------


@pytest.mark.asyncio
async def test_sla_breach_tick_enqueues_once(
    _e2e_env: None,
    admin_session: AsyncSession,
) -> None:
    user, tid, _pw = await seed_tenant_with_admin(admin_session)
    try:
        await _seed_rule(
            admin_session,
            tenant_id=tid,
            category_code="kargo",
            notify_email="sla-ops@example.com",
            sla_hours=1,
        )
        kargo_id = await _global_category_id(admin_session, "kargo")
        opened = datetime.now(UTC) - timedelta(hours=2)
        async with admin_session.begin():
            await _bind(admin_session, tid)
            ticket = Ticket(
                tenant_id=tid,
                category_id=kargo_id,
                title="Kargo gecikti",
                state=TicketState.OPEN,
                opened_at=opened,
                last_state_change_at=opened,
            )
            admin_session.add(ticket)
            await admin_session.flush()
            ticket_id = ticket.id

        engine = create_engine("admin")
        factory = create_session_factory(engine)
        try:
            await sla_breach_tick(_worker_ctx(factory))
            # İkinci koşum — NOT EXISTS koruması ikinci satırı engeller.
            await sla_breach_tick(_worker_ctx(factory))
        finally:
            await engine.dispose()

        async with admin_session.begin():
            await _bind(admin_session, tid)
            rows = (
                await admin_session.execute(
                    select(EmailOutbox).where(
                        EmailOutbox.related_ticket_id == ticket_id,
                        EmailOutbox.event_type
                        == EmailOutboxEventType.SLA_BREACH,
                    )
                )
            ).scalars().all()
        assert len(rows) == 1
        assert rows[0].to_email == "sla-ops@example.com"
        assert rows[0].status == EmailOutboxStatus.PENDING
        assert "SLA" in rows[0].subject
    finally:
        await cleanup_tenant(admin_session, user.id, tid)


# --- 5. email_outbox_tick ------------------------------------------------


async def _seed_outbox_row(
    admin_session: AsyncSession, *, tenant_id: UUID
) -> UUID:
    async with admin_session.begin():
        await _bind(admin_session, tenant_id)
        row = EmailOutbox(
            tenant_id=tenant_id,
            to_email="alici@example.com",
            subject="[İmga] Test",
            body_text="test govdesi",
            event_type=EmailOutboxEventType.TICKET_OPENED,
        )
        admin_session.add(row)
        await admin_session.flush()
        row_id = row.id
    return row_id


async def _fetch_outbox_row(
    admin_session: AsyncSession, tenant_id: UUID, row_id: UUID
) -> EmailOutbox:
    async with admin_session.begin():
        await _bind(admin_session, tenant_id)
        row = (
            await admin_session.execute(
                select(EmailOutbox).where(EmailOutbox.id == row_id)
            )
        ).scalar_one()
        admin_session.expunge(row)
    return row


@pytest.mark.asyncio
async def test_email_outbox_tick_noop_without_smtp(
    _e2e_env: None,
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, _pw = await seed_tenant_with_admin(admin_session)
    try:
        row_id = await _seed_outbox_row(admin_session, tenant_id=tid)
        monkeypatch.delenv("IMGA_SMTP_HOST", raising=False)

        engine = create_engine("admin")
        factory = create_session_factory(engine)
        try:
            await email_outbox_tick(_worker_ctx(factory))
        finally:
            await engine.dispose()

        row = await _fetch_outbox_row(admin_session, tid, row_id)
        assert row.status == EmailOutboxStatus.PENDING
        assert row.attempts == 0
        assert row.sent_at is None
    finally:
        await cleanup_tenant(admin_session, user.id, tid)


@pytest.mark.asyncio
async def test_email_outbox_tick_sends_with_fake_smtp(
    _e2e_env: None,
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, _pw = await seed_tenant_with_admin(admin_session)
    try:
        row_id = await _seed_outbox_row(admin_session, tenant_id=tid)

        sent: list[dict[str, str]] = []

        async def _fake_send(
            *, to_email: str, subject: str, body_text: str
        ) -> None:
            sent.append(
                {
                    "to_email": to_email,
                    "subject": subject,
                    "body_text": body_text,
                }
            )

        monkeypatch.setenv("IMGA_SMTP_HOST", "smtp.test.local")
        monkeypatch.setattr(email_sender, "send_email", _fake_send)

        engine = create_engine("admin")
        factory = create_session_factory(engine)
        try:
            await email_outbox_tick(_worker_ctx(factory))
        finally:
            await engine.dispose()

        # Paylaşılan test DB'sinde başka pending satırlar da gönderilmiş
        # olabilir — yalnız kendi satırımızı doğrularız.
        ours = [s for s in sent if s["to_email"] == "alici@example.com"]
        assert len(ours) == 1
        row = await _fetch_outbox_row(admin_session, tid, row_id)
        assert row.status == EmailOutboxStatus.SENT
        assert row.sent_at is not None
        assert row.last_error is None
    finally:
        await cleanup_tenant(admin_session, user.id, tid)
