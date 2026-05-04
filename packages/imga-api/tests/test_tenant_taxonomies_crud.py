"""Sprint 8.3.7-A — tenant taxonomy CRUD route tests.

Coverage matrix:

  * read: list (active only / include_inactive)
  * create: happy path, validation (code regex, label, keywords cap),
            duplicate code, parent_code reference
  * update: label / keywords / priority / parent_code; system-row
            edits allowed
  * delete: soft delete (is_active=false), idempotent re-delete
  * restore: restored row reappears in active list
  * reorder: drag-style ordered_ids → priority assignment
  * audit log: each mutation emits one taxonomy_edit_audit row

The 21 default seed rows are present after ``semi_auto_tenant`` runs
(TenantService.create seeds them); tests exercise both system rows
and tenant-added rows where the distinction matters.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- list -------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_taxonomies_returns_seeded_21(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get("/tenants/me/taxonomies", headers=_auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 21
    # All rows arrive marked is_default_seed=True since they came from
    # the platform seed at tenant creation.
    assert all(row["is_default_seed"] for row in data)
    assert all(row["is_active"] for row in data)


@pytest.mark.asyncio
async def test_list_excludes_inactive_by_default(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    # Soft-delete one seeded row.
    initial = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    target_id = initial[0]["id"]
    r = batch_client.delete(
        f"/tenants/me/taxonomies/{target_id}", headers=_auth(token)
    )
    assert r.status_code == 200

    active = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    assert len(active) == 20
    assert all(row["id"] != target_id for row in active)

    full = batch_client.get(
        "/tenants/me/taxonomies?include_inactive=true",
        headers=_auth(token),
    ).json()
    assert len(full) == 21
    inactive_row = next(row for row in full if row["id"] == target_id)
    assert inactive_row["is_active"] is False


# --- create -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_taxonomy_happy_path(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": "custom_test",
            "label_tr": "Test Kategori",
            "keywords": ["test", "deneme"],
            "priority": 50,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "custom_test"
    assert body["label_tr"] == "Test Kategori"
    assert body["keywords"] == ["test", "deneme"]
    assert body["is_default_seed"] is False
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_rejects_invalid_code_regex(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": "Bad-Case",  # uppercase + dash, both rejected
            "label_tr": "x",
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_rejects_duplicate_code(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Codes are unique per tenant — colliding with a seeded code is
    a 409, not a silent overwrite."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={"code": "shipment_not_arrived", "label_tr": "x"},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_create_normalises_keywords_lowercase_and_dedupes(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": "norm_test",
            "label_tr": "Normalize",
            "keywords": ["KARGO", "kargo", " teslimat ", "teslimat"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["keywords"] == ["kargo", "teslimat"]


@pytest.mark.asyncio
async def test_create_rejects_keywords_over_limit(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": "over_kw",
            "label_tr": "Over",
            "keywords": [f"kw{i}" for i in range(51)],
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_with_parent_code_validates_existence(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    # Existing parent → ok.
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": "child_ok",
            "label_tr": "Child",
            "parent_code": "shipment_not_arrived",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["parent_code"] == "shipment_not_arrived"

    # Missing parent → 400.
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={
            "code": "child_bad",
            "label_tr": "Child",
            "parent_code": "no_such_code",
        },
    )
    assert r.status_code == 400, r.text


# --- update -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_label_and_keywords(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    target = rows[0]

    r = batch_client.patch(
        f"/tenants/me/taxonomies/{target['id']}",
        headers=_auth(token),
        json={
            "label_tr": "Yeni Etiket",
            "keywords": ["yeni", "kelime"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["label_tr"] == "Yeni Etiket"
    assert r.json()["keywords"] == ["yeni", "kelime"]


@pytest.mark.asyncio
async def test_update_system_row_is_allowed(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """System rows can have label/keywords edited — the protection is
    only against hard delete (which the API doesn't expose anyway)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    seeded = next(r for r in rows if r["is_default_seed"])

    r = batch_client.patch(
        f"/tenants/me/taxonomies/{seeded['id']}",
        headers=_auth(token),
        json={"label_tr": "Tenant override"},
    )
    assert r.status_code == 200
    # is_default_seed stays True even after the edit; row's "system"
    # status describes its origin, not its mutability.
    assert r.json()["is_default_seed"] is True
    assert r.json()["label_tr"] == "Tenant override"


# --- delete + restore -------------------------------------------------


@pytest.mark.asyncio
async def test_delete_then_restore_round_trip(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    target = rows[0]

    r = batch_client.delete(
        f"/tenants/me/taxonomies/{target['id']}", headers=_auth(token)
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    r = batch_client.post(
        f"/tenants/me/taxonomies/{target['id']}/restore",
        headers=_auth(token),
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True


@pytest.mark.asyncio
async def test_delete_is_idempotent(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    target_id = rows[0]["id"]

    first = batch_client.delete(
        f"/tenants/me/taxonomies/{target_id}", headers=_auth(token)
    )
    second = batch_client.delete(
        f"/tenants/me/taxonomies/{target_id}", headers=_auth(token)
    )
    assert first.status_code == 200
    assert second.status_code == 200
    # Both responses report is_active=False; second call doesn't 404.
    assert first.json()["is_active"] is False
    assert second.json()["is_active"] is False


# --- reorder ----------------------------------------------------------


@pytest.mark.asyncio
async def test_reorder_assigns_priorities_by_position(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    # Reverse the current order; first row becomes priority 0, etc.
    ordered_ids = list(reversed([r["id"] for r in rows]))

    r = batch_client.put(
        "/tenants/me/taxonomies/reorder",
        headers=_auth(token),
        json={"ordered_ids": ordered_ids},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row["id"] for row in body] == ordered_ids
    assert [row["priority"] for row in body] == list(range(len(rows)))


@pytest.mark.asyncio
async def test_reorder_rejects_unknown_id(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    bad_ids = [r["id"] for r in rows] + [
        "00000000-0000-0000-0000-000000000000",
    ]
    r = batch_client.put(
        "/tenants/me/taxonomies/reorder",
        headers=_auth(token),
        json={"ordered_ids": bad_ids},
    )
    assert r.status_code == 400, r.text


# --- 404 + tenant isolation -------------------------------------------


@pytest.mark.asyncio
async def test_update_unknown_id_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.patch(
        "/tenants/me/taxonomies/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
        json={"label_tr": "x"},
    )
    assert r.status_code == 404, r.text


# --- audit log --------------------------------------------------------


@pytest.mark.asyncio
async def test_create_emits_audit_row(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/taxonomies",
        headers=_auth(token),
        json={"code": "audit_create", "label_tr": "Audit Create"},
    )
    assert r.status_code == 201
    new_id = r.json()["id"]

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                text(
                    "SELECT action, before_state, after_state, user_id "
                    "FROM taxonomy_edit_audit "
                    "WHERE taxonomy_id = :tid"
                ),
                {"tid": new_id},
            )
        ).all()
    assert len(rows) == 1
    action, before, after, audit_user = rows[0]
    assert action == "create"
    assert before is None
    assert after["code"] == "audit_create"
    assert audit_user is not None  # API path always carries a user


@pytest.mark.asyncio
async def test_update_emits_audit_with_diff(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    target_id = rows[0]["id"]
    original_label = rows[0]["label_tr"]

    r = batch_client.patch(
        f"/tenants/me/taxonomies/{target_id}",
        headers=_auth(token),
        json={"label_tr": "Yeni"},
    )
    assert r.status_code == 200

    async with admin_session.begin():
        audit_rows = (
            await admin_session.execute(
                text(
                    "SELECT action, before_state, after_state "
                    "FROM taxonomy_edit_audit "
                    "WHERE taxonomy_id = :tid AND action = 'update'"
                ),
                {"tid": target_id},
            )
        ).all()
    assert len(audit_rows) == 1
    action, before, after = audit_rows[0]
    assert action == "update"
    assert before["label_tr"] == original_label
    assert after["label_tr"] == "Yeni"


@pytest.mark.asyncio
async def test_delete_emits_audit_then_restore_emits_audit(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rows = batch_client.get(
        "/tenants/me/taxonomies", headers=_auth(token)
    ).json()
    target_id = rows[0]["id"]

    batch_client.delete(
        f"/tenants/me/taxonomies/{target_id}", headers=_auth(token)
    )
    batch_client.post(
        f"/tenants/me/taxonomies/{target_id}/restore",
        headers=_auth(token),
    )

    async with admin_session.begin():
        actions = [
            row[0]
            for row in (
                await admin_session.execute(
                    text(
                        "SELECT action FROM taxonomy_edit_audit "
                        "WHERE taxonomy_id = :tid "
                        "ORDER BY created_at"
                    ),
                    {"tid": target_id},
                )
            ).all()
        ]
    assert actions == ["delete", "restore"]


# --- migration 0020 schema regression ---------------------------------


@pytest.mark.asyncio
async def test_migration_0020_added_parent_code_and_is_active(
    admin_session: AsyncSession,
) -> None:
    """Schema regression: the new columns exist on category_taxonomies."""
    async with admin_session.begin():
        cols = {
            row[0]
            for row in (
                await admin_session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'category_taxonomies'"
                    )
                )
            ).all()
        }
    assert "parent_code" in cols
    assert "is_active" in cols


@pytest.mark.asyncio
async def test_migration_0020_created_audit_table_with_rls(
    admin_session: AsyncSession,
) -> None:
    """taxonomy_edit_audit exists, has RLS enabled + FORCE ROW LEVEL
    SECURITY (so the imga_admin role still respects the policy)."""
    async with admin_session.begin():
        rls = (
            await admin_session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'taxonomy_edit_audit'"
                )
            )
        ).first()
    assert rls is not None
    assert rls[0] is True
    assert rls[1] is True


@pytest.mark.asyncio
async def test_migration_0020_created_sla_rules_table_with_rls(
    admin_session: AsyncSession,
) -> None:
    async with admin_session.begin():
        rls = (
            await admin_session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'sla_rules'"
                )
            )
        ).first()
    assert rls is not None
    assert rls[0] is True
    assert rls[1] is True


@pytest.mark.asyncio
async def test_f18_canonical_seed_applied_to_existing_tenants(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 8.3.7-A canonical seed: tense varyantları (F18) are
    present on the tenant's seeded shipment_not_arrived row."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        keywords_row = (
            await admin_session.execute(
                text(
                    "SELECT keywords FROM category_taxonomies "
                    "WHERE tenant_id = :t AND code = 'shipment_not_arrived'"
                ),
                {"t": str(tid)},
            )
        ).first()
    assert keywords_row is not None
    keywords = list(keywords_row[0])
    assert "gelmiyor" in keywords
    assert "ulaşamıyorum" in keywords


