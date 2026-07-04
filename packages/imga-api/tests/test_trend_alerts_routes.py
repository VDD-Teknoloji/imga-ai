"""Sprint 8.3.10 — trend alerts CRUD route tests.

The TrendAlertService.evaluate runs three threshold rules over
review windows; we exercise the route's permission + status-update
surface here. Engine math is deferred to direct service tests
when needed.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import TrendAlert, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_evaluate_returns_empty_for_clean_tenant(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Fresh tenant has zero reviews → no thresholds breach → empty
    alerts. The endpoint still returns 201 (it ran successfully)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/trend-alerts/evaluate", headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_default_filter_is_active(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Seed two alerts (active + dismissed); default list shows only
    active."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        active = TrendAlert(
            tenant_id=tid,
            alert_type="nps_drop_week",
            severity="warning",
            title="Aktif",
            description="…",
            evidence={},
            status="active",
        )
        dismissed = TrendAlert(
            tenant_id=tid,
            alert_type="nps_drop_week",
            severity="warning",
            title="Atılmış",
            description="…",
            evidence={},
            status="dismissed",
        )
        admin_session.add_all([active, dismissed])

    rows = batch_client.get(
        "/tenants/me/trend-alerts", headers=_auth(token)
    ).json()
    assert {r["title"] for r in rows} == {"Aktif"}

    all_rows = batch_client.get(
        "/tenants/me/trend-alerts?status_filter=all", headers=_auth(token)
    ).json()
    assert {r["title"] for r in all_rows} == {"Aktif", "Atılmış"}


@pytest.mark.asyncio
async def test_acknowledge_alert_stamps_user_and_timestamp(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        alert = TrendAlert(
            tenant_id=tid,
            alert_type="negative_sentiment_jump",
            severity="warning",
            title="Negatif sıçrama",
            description="…",
            evidence={},
            status="active",
        )
        admin_session.add(alert)
        await admin_session.flush()
        alert_id = str(alert.id)

    r = batch_client.patch(
        f"/tenants/me/trend-alerts/{alert_id}",
        headers=_auth(token),
        json={"status": "acknowledged"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "acknowledged"
    assert body["acknowledged_by_user_id"] == str(user.id)
    assert body["acknowledged_at"] is not None


@pytest.mark.asyncio
async def test_invalid_status_filter_returns_400(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/trend-alerts?status_filter=foo", headers=_auth(token)
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_status_update_returns_422(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        alert = TrendAlert(
            tenant_id=tid,
            alert_type="x",
            severity="info",
            title="Y",
            description="Z",
            evidence={},
            status="active",
        )
        admin_session.add(alert)
        await admin_session.flush()
        alert_id = str(alert.id)

    r = batch_client.patch(
        f"/tenants/me/trend-alerts/{alert_id}",
        headers=_auth(token),
        json={"status": "snoozed"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_viewer_cannot_acknowledge_alert(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 13 rol matrisi: ack/dismiss durum mutasyonu — VIEWER
    (salt-okuma) 403 almalı; listeleme serbest kalır."""
    from uuid import uuid4

    from imga_db.models import TrendAlert as _TA, UserTenantRole

    from imga_api.services import AuditService, UserService

    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        alert = _TA(
            tenant_id=tid,
            alert_type="nps_drop_week",
            severity="warning",
            title="Viewer testi",
            description="…",
            evidence={},
            status="active",
        )
        admin_session.add(alert)
        await admin_session.flush()
        alert_id = str(alert.id)

    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    viewer_plain = "Viewer-Password-123!"
    viewer_email = f"viewer-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=viewer_email, password=viewer_plain, full_name="TA Viewer"
        )
        await usvc.attach_to_tenant(
            user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER
        )
        viewer_id = viewer.id

    try:
        token = login_token(batch_client, viewer_email, viewer_plain, tid)
        list_r = batch_client.get(
            "/tenants/me/trend-alerts", headers=_auth(token)
        )
        assert list_r.status_code == 200, list_r.text

        r = batch_client.patch(
            f"/tenants/me/trend-alerts/{alert_id}",
            headers=_auth(token),
            json={"status": "acknowledged"},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(viewer_id)},
            )
