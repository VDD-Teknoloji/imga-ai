"""ApiTokenService — DB testleri (:5433 canlı-Postgres).

Ops token yaşam döngüsü admin_tokens'da tenant FK gerektirmez → admin_session
(BYPASSRLS) ile self-contained. Tenant token + RLS testleri ayrı (e2e_seed
tenant'ı gerektirir; sonraki dilim).
"""

from __future__ import annotations

import uuid

import pytest

from imga_db.models import AdminTokenRecord

from imga_api.services.api_tokens import ApiTokenService, TokenServiceError

_PEPPER = "p" * 40


def test_service_requires_pepper() -> None:
    with pytest.raises(TokenServiceError):
        ApiTokenService(pepper="", environment="staging")
    with pytest.raises(TokenServiceError):
        ApiTokenService(pepper="short", environment="staging")


@pytest.mark.asyncio
async def test_ops_token_mint_verify_revoke(admin_session) -> None:
    svc = ApiTokenService(pepper=_PEPPER, environment="staging")

    async with admin_session.begin():
        minted = await svc.mint(admin_session, scope="ops", label="ops-test")
    assert minted.plaintext.startswith("imga_ops_stg_")
    assert minted.last4 == minted.plaintext[-4:]

    async with admin_session.begin():
        row = await svc.verify(admin_session, minted.plaintext)
    assert isinstance(row, AdminTokenRecord)
    assert row.id == minted.token_id
    assert row.scope == "ops"

    async with admin_session.begin():
        rev = await svc.revoke(admin_session, minted.token_id, reason="test")
    assert rev is not None
    assert rev.propagation_deadline > rev.revoked_at

    # revoke sonrası verify None
    async with admin_session.begin():
        row2 = await svc.verify(admin_session, minted.plaintext)
    assert row2 is None


@pytest.mark.asyncio
async def test_verify_wrong_token_none(admin_session) -> None:
    svc = ApiTokenService(pepper=_PEPPER, environment="staging")
    async with admin_session.begin():
        assert await svc.verify(admin_session, "imga_ops_stg_notarealtoken") is None
        assert await svc.verify(admin_session, "garbage") is None


@pytest.mark.asyncio
async def test_mint_validations(admin_session) -> None:
    svc = ApiTokenService(pepper=_PEPPER, environment="production")
    # tenant scope tenant_id ister
    with pytest.raises(TokenServiceError):
        await svc.mint(admin_session, scope="tenant", label="x")
    # ops token tenant_id taşımaz
    with pytest.raises(TokenServiceError):
        await svc.mint(
            admin_session, scope="ops", label="x", tenant_id=uuid.uuid4()
        )
    # ttl > 365
    with pytest.raises(TokenServiceError):
        await svc.mint(admin_session, scope="ops", label="x", ttl_days=400)


@pytest.mark.asyncio
async def test_revoke_unknown_returns_none(admin_session) -> None:
    svc = ApiTokenService(pepper=_PEPPER, environment="staging")
    async with admin_session.begin():
        assert await svc.revoke(admin_session, uuid.uuid4()) is None
