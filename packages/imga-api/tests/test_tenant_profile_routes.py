"""Sprint 8.3.6.5 — tenant profile route tests.

Three focused tests on the validators that gate the SWOT/OKR prompt
context fields.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User

from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_update_profile_persists_fields(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = batch_client.patch(
        "/tenants/me/profile",
        headers=headers,
        json={
            "industry": "e_commerce",
            "company_size": "medium",
            "business_description": "Türkiye genelinde online satış",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["industry"] == "e_commerce"
    assert body["company_size"] == "medium"
    assert body["business_description"] == "Türkiye genelinde online satış"

    # Round-trip via GET.
    r2 = batch_client.get("/tenants/me/profile", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["industry"] == "e_commerce"


@pytest.mark.asyncio
async def test_update_profile_industry_other_requires_text(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Hybrid enum: ``industry='other'`` without ``industry_other_text``
    must 422 (Pydantic validator)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.patch(
        "/tenants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"industry": "other"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_update_profile_with_industry_other_and_text_succeeds(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.patch(
        "/tenants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"industry": "other", "industry_other_text": "Kuyumculuk"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["industry"] == "other"
    assert body["industry_other_text"] == "Kuyumculuk"
