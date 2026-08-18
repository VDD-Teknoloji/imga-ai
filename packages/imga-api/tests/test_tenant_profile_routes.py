"""Sprint 8.3.6.5 — tenant profile route tests.

Three focused tests on the validators that gate the SWOT/OKR prompt
context fields.

2026-08-18 (WS1/WS3, migration 0042) — ``terminology`` (sektör terim
sözlüğü) GET/PATCH coverage: full-replace semantics + doğrulama (en
çok 50 madde, ``term`` zorunlu/boş olamaz). Onboarding'in tenant-
create yolu ``terminology``'yi zaten yazabiliyordu (B3); bu, kuruluş
sonrası düzenleme yüzeyi.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest.mark.asyncio
async def test_get_profile_terminology_defaults_to_null(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Yeni kurumlar (henüz sözlük doldurmamış) terminology=None
    görür — mevcut davranış hiç değişmez."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["terminology"] is None


@pytest.mark.asyncio
async def test_update_profile_terminology_full_replace_round_trip(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """2026-08-18 (WS3) — PATCH tam-değiştirme semantiği: ikinci PATCH
    ilk listeyi TAMAMEN değiştirir (per-entry merge YOK)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = batch_client.patch(
        "/tenants/me/profile",
        headers=headers,
        json={
            "terminology": [
                {"term": "SLA", "note": "Servis seviyesi anlaşması"},
                {"term": "NPS"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["terminology"] == [
        {"term": "SLA", "note": "Servis seviyesi anlaşması"},
        {"term": "NPS"},
    ]

    # Round-trip via GET.
    r2 = batch_client.get("/tenants/me/profile", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["terminology"] == body["terminology"]

    # İkinci PATCH: eskisiyle birleşmez, TAMAMEN değişir.
    r3 = batch_client.patch(
        "/tenants/me/profile",
        headers=headers,
        json={"terminology": [{"term": "OKR"}]},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["terminology"] == [{"term": "OKR"}]

    r4 = batch_client.get("/tenants/me/profile", headers=headers)
    assert r4.json()["terminology"] == [{"term": "OKR"}]

    # Explicit null temizler.
    r5 = batch_client.patch(
        "/tenants/me/profile",
        headers=headers,
        json={"terminology": None},
    )
    assert r5.status_code == 200, r5.text
    assert r5.json()["terminology"] is None


@pytest.mark.asyncio
async def test_update_profile_terminology_rejects_blank_term(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.patch(
        "/tenants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"terminology": [{"term": "   "}]},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_update_profile_terminology_requires_term_field(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.patch(
        "/tenants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"terminology": [{"note": "term alani hic yok"}]},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_update_profile_terminology_rejects_over_50_entries(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.patch(
        "/tenants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"terminology": [{"term": f"t{i}"} for i in range(51)]},
    )
    assert r.status_code == 422, r.text

    # Sınırdaki 50 madde kabul edilir.
    r2 = batch_client.patch(
        "/tenants/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"terminology": [{"term": f"t{i}"} for i in range(50)]},
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["terminology"]) == 50


@pytest.mark.asyncio
async def test_update_profile_terminology_viewer_forbidden(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Yazma yetkisi tenant_admin + analyst ile sınırlı (mevcut rol
    deseni, bkz. test_analyze_audit_integration.test_viewer_cannot_analyze) —
    viewer PATCH edemez."""
    from uuid import uuid4

    from imga_db.models import UserTenantRole

    from imga_api.services import AuditService, UserService

    _admin, tid, _pw = semi_auto_tenant

    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    viewer_plain = "Viewer-Password-123!"
    viewer_email = f"viewer-terminology-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=viewer_email, password=viewer_plain, full_name="Terminology Viewer"
        )
        await usvc.attach_to_tenant(
            user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER
        )
        viewer_id = viewer.id

    try:
        token = login_token(batch_client, viewer_email, viewer_plain, tid)
        r = batch_client.patch(
            "/tenants/me/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"terminology": [{"term": "SLA"}]},
        )
        assert r.status_code == 403, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": str(viewer_id)},
            )
