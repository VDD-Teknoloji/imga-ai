"""Sprint 8.3.7-A — SLA rules CRUD route tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User

from tests.batch_helpers import login_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_sla_rule_happy_path(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={
            "name": "Yüksek öncelikli yanıt",
            "match_priority": "high",
            "response_sla_minutes": 60,
            "action_type": "warn_only",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Yüksek öncelikli yanıt"
    assert body["match_priority"] == "high"
    assert body["response_sla_minutes"] == 60
    assert body["action_type"] == "warn_only"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_rejects_when_no_threshold_set(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """At least one of response_sla_minutes / resolution_sla_minutes
    must be set; otherwise Pydantic 422s before reaching the DB."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={"name": "Eşiksiz", "action_type": "warn_only"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_rejects_invalid_priority(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={
            "name": "Bad priority",
            "match_priority": "critical",  # not in low/normal/high/urgent
            "response_sla_minutes": 30,
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_list_returns_only_active_by_default(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    # Two rules, one of which we'll deactivate.
    a = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={"name": "Rule A", "response_sla_minutes": 30},
    ).json()
    b = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={"name": "Rule B", "response_sla_minutes": 60},
    ).json()
    batch_client.delete(
        f"/tenants/me/sla-rules/{a['id']}", headers=_auth(token)
    )

    active = batch_client.get(
        "/tenants/me/sla-rules", headers=_auth(token)
    ).json()
    full = batch_client.get(
        "/tenants/me/sla-rules?include_inactive=true", headers=_auth(token)
    ).json()
    assert {r["id"] for r in active} == {b["id"]}
    assert {r["id"] for r in full} == {a["id"], b["id"]}


@pytest.mark.asyncio
async def test_update_rule_partial_patch(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rule = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={"name": "Patchable", "response_sla_minutes": 60},
    ).json()

    r = batch_client.patch(
        f"/tenants/me/sla-rules/{rule['id']}",
        headers=_auth(token),
        json={"name": "Renamed", "resolution_sla_minutes": 240},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["response_sla_minutes"] == 60  # unchanged
    assert body["resolution_sla_minutes"] == 240


@pytest.mark.asyncio
async def test_update_clearing_both_thresholds_returns_400(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rule = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={"name": "Patchable", "response_sla_minutes": 60},
    ).json()
    r = batch_client.patch(
        f"/tenants/me/sla-rules/{rule['id']}",
        headers=_auth(token),
        json={
            "response_sla_minutes": None,
            "resolution_sla_minutes": None,
        },
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_create_with_unwired_action_type_succeeds(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """create_ticket is wired in Sprint 8.3.9 — but tenants can draft
    the rule now. The DB CHECK accepts the value; the engine raises
    NotImplementedError when actually executing it."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={
            "name": "Ticket draft",
            "response_sla_minutes": 60,
            "action_type": "create_ticket",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["action_type"] == "create_ticket"


@pytest.mark.asyncio
async def test_delete_rule_marks_inactive(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rule = batch_client.post(
        "/tenants/me/sla-rules",
        headers=_auth(token),
        json={"name": "Soft me", "resolution_sla_minutes": 240},
    ).json()
    r = batch_client.delete(
        f"/tenants/me/sla-rules/{rule['id']}", headers=_auth(token)
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False
