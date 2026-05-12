"""Sprint 9.5 B2 — action_items idempotency regression tests.

Two endpoints, two contracts:

  1. ``POST /tenants/me/action-items`` — manual create with an
     optional ``Idempotency-Key`` request header. Retries with the
     same key + tenant return the existing row instead of inserting
     a duplicate. Legacy / non-keyed callers retain the pre-9.5
     behaviour (every call mints a fresh row).

  2. ``POST /tenants/me/action-items/extract-from-report/{id}`` —
     re-extracting the same SWOT used to mint duplicate ActionItems
     on every call. The route now routes through
     ``ActionExtractionService`` which fingerprint-dedups on
     ``(tenant_id, source_type, source_id, content_hash)``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import ActionItem, StrategicReport, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


# --- /tenants/me/action-items + Idempotency-Key -------------------------


@pytest.mark.asyncio
async def test_create_action_item_with_idempotency_key_returns_same_row(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Two requests with the same Idempotency-Key + tenant short-
    circuit to the first row. Critical for network-retry safety —
    the frontend posts with a UUID key on submit; a transient 502
    on the original request, followed by retry, must NOT mint two
    rows."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    key = f"ik-{uuid4().hex[:16]}"
    body = {
        "title": "Yeniden ölç",
        "description": "Kargo süresini 2 günden 1 güne indir",
        "priority": "high",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": key,
    }

    r1 = batch_client.post(
        "/tenants/me/action-items", headers=headers, json=body,
    )
    assert r1.status_code == 201, r1.text
    first_id = r1.json()["id"]

    r2 = batch_client.post(
        "/tenants/me/action-items", headers=headers, json=body,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["id"] == first_id, (
        "Second call with same Idempotency-Key must reuse the first "
        "row's id. If it mints a new id, the partial UNIQUE index "
        "isn't being consulted before the INSERT."
    )

    # DB sanity — exactly one row for the key.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(ActionItem).where(
                    ActionItem.tenant_id == tid,
                    ActionItem.idempotency_key == key,
                )
            )
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_action_item_without_key_still_mints_fresh(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Backwards-compat: legacy clients (no header) still get a
    fresh row per call. The partial UNIQUE index only covers
    non-NULL keys so NULLs don't collide with each other."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    body = {
        "title": "Unique title 1",
        "description": "Açıklama 1",
        "priority": "medium",
    }
    headers = {"Authorization": f"Bearer {token}"}

    r1 = batch_client.post(
        "/tenants/me/action-items", headers=headers, json=body,
    )
    r2 = batch_client.post(
        "/tenants/me/action-items", headers=headers, json=body,
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"], (
        "no-key clients should still mint fresh rows; the partial "
        "UNIQUE excludes NULL ``idempotency_key`` rows"
    )


@pytest.mark.asyncio
async def test_idempotency_keys_scoped_per_tenant(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """The UNIQUE constraint is composite — (tenant_id,
    idempotency_key). Tenant A using key 'xyz' must not block
    tenant B from using the same key value."""
    from tests.batch_helpers import seed_tenant_with_admin

    user_a, tid_a, pw_a = semi_auto_tenant
    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Other Co",
    )
    token_a = login_token(batch_client, user_a.email, pw_a, tid_a)
    token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
    shared_key = "shared-key-across-tenants"
    body = {
        "title": "X",
        "description": "Y",
        "priority": "medium",
    }

    r_a = batch_client.post(
        "/tenants/me/action-items",
        headers={
            "Authorization": f"Bearer {token_a}",
            "Idempotency-Key": shared_key,
        },
        json=body,
    )
    r_b = batch_client.post(
        "/tenants/me/action-items",
        headers={
            "Authorization": f"Bearer {token_b}",
            "Idempotency-Key": shared_key,
        },
        json=body,
    )
    assert r_a.status_code == 201
    assert r_b.status_code == 201
    assert r_a.json()["id"] != r_b.json()["id"], (
        "Same idempotency key across DIFFERENT tenants must yield "
        "distinct rows. If the constraint isn't composite, this "
        "fails with a UNIQUE-violation 500 or a wrong-tenant return."
    )


# --- /extract-from-report dedup -----------------------------------------


async def _seed_swot(
    admin_session: AsyncSession,
    tenant_id: UUID,
) -> UUID:
    """Insert a minimal SWOT row with two strategic_recommendations
    so the extract endpoint has content to chew on."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        row = StrategicReport(
            tenant_id=tenant_id,
            report_type="swot",
            input_stats={},
            model_name="test-model",
            output_payload={
                "strategic_recommendations": [
                    {
                        "title": "Kargo SLA'yı 3'ten 2 güne indir",
                        "description": "Üçüncü gün şikayetleri yarıya düşer.",
                        "priority": "high",
                        "estimated_impact": "high",
                    },
                    {
                        "title": "İade portalı UX revize",
                        "description": "Müşteri ev adresi alanı zorunlu olsun.",
                        "priority": "medium",
                        "estimated_impact": "medium",
                    },
                ],
            },
        )
        admin_session.add(row)
        await admin_session.flush()
        report_id = row.id
        admin_session.expunge(row)
    return report_id


@pytest.mark.asyncio
async def test_extract_from_report_twice_returns_same_action_items(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Pre-9.5 the route minted fresh rows on every call —
    "calling extract twice doubles the rows" was a documented
    limitation. Post-9.5 the ActionExtractionService fingerprint
    layer keeps the row set stable across re-extracts of the same
    SWOT content."""
    user, tid, pw = semi_auto_tenant
    report_id = await _seed_swot(admin_session, tid)
    token = login_token(batch_client, user.email, pw, tid)

    r1 = batch_client.post(
        f"/tenants/me/action-items/extract-from-report/{report_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    r2 = batch_client.post(
        f"/tenants/me/action-items/extract-from-report/{report_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    ids_a = {item["id"] for item in r1.json()}
    ids_b = {item["id"] for item in r2.json()}
    assert ids_a == ids_b, (
        "Second extract MUST return the same action_item_ids as "
        "the first; if they diverge the ActionExtractionService "
        "fingerprint isn't matching across calls (different "
        "content_text serialisation? extraction_version drift?)"
    )

    # DB sanity — only one set of rows tied to this SWOT.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(ActionItem).where(
                    ActionItem.tenant_id == tid,
                    ActionItem.source_report_id == report_id,
                )
            )
        ).scalars().all()
    assert len(rows) == 2, (
        f"Expected exactly 2 action items per SWOT extract; got "
        f"{len(rows)}. If 4, the dedup isn't working and the row "
        "set is doubling on the second call."
    )
