"""§8 admin auth ↔ handler paylaşılan-session regresyonu (prod C1/C2 bug'ı).

Prod'da `POST /v1/admin/tenants` ve `/v1/admin/tokens/rotate` 500 döndü:
``sqlalchemy.exc.InvalidRequestError: A transaction is already begun on this
Session``. Kök neden: `get_partner_principal` içindeki `verify()` bir SELECT
koşup (AsyncSession autobegin) admin_session'da transaction AÇIK bırakıyor; bu
session FastAPI dependency-cache'iyle handler'la paylaşılıyor ve handler
`async with admin_session.begin()` çağırınca çakışıyor. Fix: auth read'i
`admin_session.rollback()` ile kapat (v1/auth.py).

Bu test ENDPOINT seviyesinde (servis-seviyesi test_api_tokens_service bunu
yakalayamadı çünkü paylaşılan dependency akışından geçmiyor). Gerçek app +
:5433 DB ister.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Settings.from_env() (e2e_client lifespan'inde) IMGA_TOKEN_PEPPER okur — app
# boot ETMEDEN, collection anında set edilmeli. min-32.
_TEST_PEPPER = "regr-pepper-0123456789abcdef0123456789abcdef"
os.environ["IMGA_TOKEN_PEPPER"] = _TEST_PEPPER


@pytest_asyncio.fixture
async def ops_bearer(admin_session: AsyncSession) -> str:
    """admin_tokens'a bir ops token INSERT et, plaintext döndür. environment
    'development' → imga_ops_stg_ öneki (settings.environment ile eşleşir)."""
    from imga_api.services.api_tokens import ApiTokenService

    svc = ApiTokenService(pepper=_TEST_PEPPER, environment="development")
    async with admin_session.begin():
        minted = await svc.mint(admin_session, scope="ops", label="regr-ops")
    return minted.plaintext


@pytest_asyncio.fixture
async def created_slugs(admin_session: AsyncSession) -> AsyncIterator[list[str]]:
    """Test'in oluşturduğu tenant slug'larını topla, teardown'da sil (CASCADE)."""
    slugs: list[str] = []
    yield slugs
    if slugs:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM tenants WHERE slug = ANY(:s)"), {"s": slugs}
            )


def test_admin_create_tenant_and_rotate_no_session_conflict(
    e2e_client: TestClient,
    ops_bearer: str,
    created_slugs: list[str],
) -> None:
    auth = {"Authorization": f"Bearer {ops_bearer}"}
    name = f"ZZZ Regr {uuid.uuid4().hex[:8]}"

    # C1 — tenant create: prod'da 500'dü, fix sonrası 201 olmalı.
    created = e2e_client.post(
        "/v1/admin/tenants",
        headers=auth,
        json={"name": name, "contact_email": "regr@example.com"},
    )
    assert created.status_code == 201, created.text
    slug = created.json()["tenant_id"]
    created_slugs.append(slug)

    # C2 — token rotate: aynı paylaşılan-session yolu, prod'da 500'dü → 200.
    rotated = e2e_client.post(
        "/v1/admin/tokens/rotate",
        headers=auth,
        json={"tenant_id": slug, "overlap_window_hours": 24},
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["new_token"].startswith("imga_stg_")


def test_admin_requires_ops_scope(e2e_client: TestClient) -> None:
    # Geçersiz/eksik bearer → 401 AnalyzeError (500 değil).
    r = e2e_client.post(
        "/v1/admin/tenants",
        json={"name": "X", "contact_email": "x@example.com"},
    )
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "auth_failed"
