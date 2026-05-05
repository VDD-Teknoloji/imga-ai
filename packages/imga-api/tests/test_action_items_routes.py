"""Sprint 8.3.10 — action items CRUD route tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import StrategicReport, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_action_item_happy_path(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/action-items",
        headers=_auth(token),
        json={
            "title": "Kargo SLA gözden geçirme",
            "description": "Kritik kargo şikayetleri için 4-saat SLA tanımla.",
            "priority": "high",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Kargo SLA gözden geçirme"
    assert body["priority"] == "high"
    assert body["status"] == "open"


@pytest.mark.asyncio
async def test_list_action_items_status_filter(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    a = batch_client.post(
        "/tenants/me/action-items",
        headers=_auth(token),
        json={"title": "A", "description": "x", "priority": "low"},
    ).json()
    b = batch_client.post(
        "/tenants/me/action-items",
        headers=_auth(token),
        json={"title": "B", "description": "y", "priority": "low"},
    ).json()
    batch_client.patch(
        f"/tenants/me/action-items/{a['id']}",
        headers=_auth(token),
        json={"status": "done"},
    )

    open_only = batch_client.get(
        "/tenants/me/action-items?status_filter=open", headers=_auth(token)
    ).json()
    done_only = batch_client.get(
        "/tenants/me/action-items?status_filter=done", headers=_auth(token)
    ).json()
    assert {r["id"] for r in open_only} == {b["id"]}
    assert {r["id"] for r in done_only} == {a["id"]}


@pytest.mark.asyncio
async def test_update_status_done_stamps_completed_at(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    item = batch_client.post(
        "/tenants/me/action-items",
        headers=_auth(token),
        json={"title": "T", "description": "D", "priority": "medium"},
    ).json()
    r = batch_client.patch(
        f"/tenants/me/action-items/{item['id']}",
        headers=_auth(token),
        json={"status": "done"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_create_rejects_invalid_priority(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/action-items",
        headers=_auth(token),
        json={"title": "X", "description": "Y", "priority": "urgent"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_delete_action_item(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    item = batch_client.post(
        "/tenants/me/action-items",
        headers=_auth(token),
        json={"title": "X", "description": "Y"},
    ).json()
    r = batch_client.delete(
        f"/tenants/me/action-items/{item['id']}", headers=_auth(token)
    )
    assert r.status_code == 204, r.text
    listing = batch_client.get(
        "/tenants/me/action-items", headers=_auth(token)
    ).json()
    assert all(row["id"] != item["id"] for row in listing)


@pytest.mark.asyncio
async def test_extract_from_swot_report_creates_action_items(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Seed a SWOT report with strategic_recommendations; extract
    endpoint creates one action_item per entry. Türkçe priority
    ('yüksek') maps to English ('high')."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    payload: dict[str, Any] = {
        "strengths": [],
        "weaknesses": [],
        "opportunities": [],
        "threats": [],
        "strategic_recommendations": [
            {
                "title": "Kargo SLA",
                "description": "5 günden 3 güne",
                "priority": "yüksek",
                "estimated_impact": "yüksek",
            },
            {
                "title": "İade portalı",
                "description": "Self-service iade akışı",
                "priority": "orta",
                "estimated_impact": "orta",
            },
        ],
    }
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        report = StrategicReport(
            tenant_id=tid,
            report_type="swot",
            input_stats={"stats_hash": "abc"},
            output_payload=payload,
            model_name="gemini-2.5-flash",
        )
        admin_session.add(report)
        await admin_session.flush()
        report_id = str(report.id)
        admin_session.expunge(report)

    r = batch_client.post(
        f"/tenants/me/action-items/extract-from-report/{report_id}",
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    rows = r.json()
    assert len(rows) == 2
    titles = {row["title"] for row in rows}
    assert titles == {"Kargo SLA", "İade portalı"}
    priorities = {row["priority"] for row in rows}
    assert priorities == {"high", "medium"}
    # Source link populated.
    for row in rows:
        assert row["source_report_id"] == report_id
