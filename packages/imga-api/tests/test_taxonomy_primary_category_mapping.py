"""Sprint 13.1 — ``category_taxonomies.primary_category_code`` CRUD.

Kapsam:
  * Varsayılan seed her satırı bir ana kategoriye eşler (migration
    0040 backfill'i ile aynı tablo).
  * POST / PATCH alanı kabul eder, GET geri döner.
  * Geçersiz kod 422 (Pydantic field_validator).
  * Açık ``null`` eşlemeyi kaldırır.
  * Alanı hiç göndermeyen PATCH mevcut eşlemeyi KORUR (parent_code'un
    ``model_fields_set`` semantiğiyle aynı).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES
from imga_db.models import User

from tests.batch_helpers import login_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_default_seed_rows_carry_primary_category_code(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Yeni kurum ``TenantService.create`` üzerinden açılıyor; 21
    varsayılan satırın hepsi bir ana kategoriye eşlenmiş olmalı ve
    her kod global listede bulunmalı."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.get("/tenants/me/taxonomies", headers=_auth(token))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 21
    for row in rows:
        assert row["primary_category_code"] in GLOBAL_CATEGORY_CODES, row

    by_code = {row["code"]: row["primary_category_code"] for row in rows}
    # İş hikâyesinin çıpası: kargo alt kategorileri kargo altında.
    assert by_code["shipment_not_arrived"] == "kargo"
    assert by_code["order_status_wrong"] == "siparis_sureci"
    assert by_code["invoice_request"] == "faturalama"
    assert by_code["how_to_return"] == "iade"


@pytest.mark.asyncio
async def test_create_accepts_and_returns_primary_category_code(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    code = f"custom_{uuid4().hex[:6]}"
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": code,
            "label_tr": "Kargo aracı bulunamadı",
            "primary_category_code": "kargo",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["primary_category_code"] == "kargo"

    listed = batch_client.get("/tenants/me/taxonomies", headers=_auth(token))
    match = next(x for x in listed.json() if x["code"] == code)
    assert match["primary_category_code"] == "kargo"


@pytest.mark.asyncio
async def test_create_rejects_unknown_primary_category_code(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Global kod uzayı dışındaki değer 422 — yoksa drill-down
    gruplaması sessizce boş kova üretirdi."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": f"custom_{uuid4().hex[:6]}",
            "label_tr": "Geçersiz eşleme",
            "primary_category_code": "kargo_lojistik",
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_accepts_null_primary_category_code(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": f"custom_{uuid4().hex[:6]}",
            "label_tr": "Eşlenmemiş alt kategori",
            "primary_category_code": None,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["primary_category_code"] is None


@pytest.mark.asyncio
async def test_patch_updates_clears_and_preserves_mapping(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Üç davranış tek testte, çünkü hepsi aynı satırın ardışık
    durumları: güncelle → açık null ile temizle → alanı hiç
    göndermeyen PATCH eşlemeyi bozmasın."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    listed = batch_client.get("/tenants/me/taxonomies", headers=_auth(token))
    row = next(
        x for x in listed.json() if x["code"] == "shipment_not_arrived"
    )
    tax_id = row["id"]

    r = batch_client.patch(
        f"/tenants/me/taxonomies/{tax_id}",
        headers=_auth(token),
        json={"primary_category_code": "musteri_hizmetleri"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_category_code"] == "musteri_hizmetleri"

    # Alanı göndermeyen PATCH eşlemeyi korur.
    r = batch_client.patch(
        f"/tenants/me/taxonomies/{tax_id}",
        headers=_auth(token),
        json={"label_tr": "Kargom ulaşmadı (güncel)"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_category_code"] == "musteri_hizmetleri"

    # Açık null eşlemeyi kaldırır.
    r = batch_client.patch(
        f"/tenants/me/taxonomies/{tax_id}",
        headers=_auth(token),
        json={"primary_category_code": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["primary_category_code"] is None


@pytest.mark.asyncio
async def test_patch_rejects_unknown_primary_category_code(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    listed = batch_client.get("/tenants/me/taxonomies", headers=_auth(token))
    tax_id = listed.json()[0]["id"]

    r = batch_client.patch(
        f"/tenants/me/taxonomies/{tax_id}",
        headers=_auth(token),
        json={"primary_category_code": "uydurma"},
    )
    assert r.status_code == 422, r.text
