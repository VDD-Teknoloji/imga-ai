"""Sprint 13.1 — kök neden analizi servisi + rotaları.

Katmanlar (test_swot_service.py'nin ayrımıyla aynı):

  * Servis: sağlayıcı enjekte edilir (``provider=`` kwarg), fakeredis
    modül singleton'ı olarak kurulur. Gerçek LLM çağrısı YOK.
  * Rota: ``RootCauseService.generate`` monkeypatch'lenir; amaç HTTP
    sarmalayıcısını (yetki + hata haritası) doğrulamak.

Transaction disiplini: her servis testi bind_tenant + generate + DB
doğrulamasını TEK ``async with admin_session.begin()`` bloğunda
yapar (conftest'in cleanup_tenant'ıyla çakışmasın).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, RootCauseAnalysis, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import set_redis_client
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.root_cause_service import (
    NotEnoughReviewsError,
    RootCauseService,
)
from tests.batch_helpers import login_token

_ENDPOINT = "/tenants/me/insights/root-cause"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis_client() -> Any:
    """In-process Redis double, installed as the module singleton."""
    import fakeredis.aioredis as fakeredis_async

    fake = fakeredis_async.FakeRedis(decode_responses=False)
    set_redis_client(fake)
    yield fake
    set_redis_client(None)


def _payload() -> dict[str, Any]:
    return {
        "summary": "Kargo statüsü yanlış gösteriliyor.",
        "root_causes": [
            {
                "title": "Uygulama statüyü yanlış gösteriyor",
                "description": (
                    "Kargo entegrasyonu 'teslim edildi' durumunu erken "
                    "yazıyor; müşteri gerçeği çağrı merkezinden öğreniyor."
                ),
                "evidence_quotes": ["Teslim edildi yazıyor ama elimde yok"],
                "affected_surface": "mobil uygulama",
                "suggested_action": "Statü senkronizasyonunu webhook'a çevir",
                "share_estimate_pct": 62,
            }
        ],
    }


def _build_mock_provider(
    *,
    payload: dict[str, Any] | None = None,
    side_effect: Exception | None = None,
) -> Any:
    """``generate_root_cause`` servisin dokunduğu tek attribute."""
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    if side_effect is not None:
        provider.generate_root_cause = AsyncMock(  # type: ignore[method-assign]
            side_effect=side_effect
        )
    else:
        provider.generate_root_cause = AsyncMock(  # type: ignore[method-assign]
            return_value=(payload or _payload(), {"input": 100, "output": 50})
        )
    return provider


async def _bind_tenant(session: AsyncSession, tid: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tid)},
    )


async def _seed_reviews(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    count: int,
    primary_category: str = "kargo",
    perspective_code: str | None = "order_status_wrong",
) -> None:
    async with admin_session.begin():
        await _bind_tenant(admin_session, tenant_id)
        for i in range(count):
            body = f"Kargo statüsü yanlış görünüyor {uuid4().hex[:8]} {i}"
            admin_session.add(
                Review(
                    tenant_id=tenant_id,
                    text=body,
                    text_hash=review_text_hash(body),
                    sentiment_label="NEGATIF",
                    sentiment_score=-0.8,
                    primary_category=primary_category,
                    primary_confidence=0.9,
                    automation_mode="semi_auto",
                    decision=ReviewDecision.SKIPPED_THRESHOLD,
                    decision_reason=None,
                    ticket_id=None,
                    submitted_by_user_id=None,
                    analyzed_at=datetime.now(UTC),
                    review_date=datetime.now(UTC),
                    company_perspective_code=perspective_code,
                )
            )
        await admin_session.flush()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_raises_without_credentials(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    fake_redis_client: Any,
) -> None:
    """Anahtar yoksa hiç LLM çağrısı denenmeden NoCredentialsError."""
    del fake_redis_client
    _user, tid, _pw = semi_auto_tenant
    await _seed_reviews(admin_session, tenant_id=tid, count=12)

    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = RootCauseService(
            admin_session, tid, None, provider=_build_mock_provider()
        )
        with pytest.raises(NoCredentialsError):
            await service.generate(
                primary_category="kargo",
                perspective_code="order_status_wrong",
            )


@pytest.mark.asyncio
async def test_service_raises_below_minimum_reviews(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """10'un altında yorum → NotEnoughReviewsError; kredi harcanmaz."""
    del fake_redis_client
    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)
    await _seed_reviews(admin_session, tenant_id=tid, count=3)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = RootCauseService(admin_session, tid, None, provider=provider)
        with pytest.raises(NotEnoughReviewsError):
            await service.generate(
                primary_category="kargo",
                perspective_code="order_status_wrong",
            )
    provider.generate_root_cause.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_generates_persists_and_caches(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)
    await _seed_reviews(admin_session, tenant_id=tid, count=14)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = RootCauseService(admin_session, tid, None, provider=provider)
        result = await service.generate(
            primary_category="kargo", perspective_code="order_status_wrong"
        )

        assert result["review_count"] == 14
        assert result["primary_category_code"] == "kargo"
        assert result["perspective_code"] == "order_status_wrong"
        assert result["payload"]["root_causes"][0]["affected_surface"] == (
            "mobil uygulama"
        )
        # En fazla 3 alıntı sözleşmesi normalizasyonda korunuyor.
        assert len(result["payload"]["root_causes"][0]["evidence_quotes"]) <= 3

        rows = (
            await admin_session.execute(
                select(RootCauseAnalysis).where(
                    RootCauseAnalysis.tenant_id == tid
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].model_provider == "gemini"

    cache_keys = await fake_redis_client.keys("root_cause:*")
    assert len(cache_keys) == 1


@pytest.mark.asyncio
async def test_service_cache_hit_skips_llm(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    del fake_redis_client
    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)
    await _seed_reviews(admin_session, tenant_id=tid, count=11)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = RootCauseService(admin_session, tid, None, provider=provider)
        await service.generate(
            primary_category="kargo", perspective_code="order_status_wrong"
        )
        assert provider.generate_root_cause.await_count == 1
        await service.generate(
            primary_category="kargo", perspective_code="order_status_wrong"
        )
        assert provider.generate_root_cause.await_count == 1


@pytest.mark.asyncio
async def test_service_unmatched_bucket_reads_null_perspective_rows(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """``__unmatched__`` sentinel'i NULL perspektifli yorumları okur."""
    del fake_redis_client
    _user, tid, _pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)
    await _seed_reviews(
        admin_session, tenant_id=tid, count=13, perspective_code=None
    )

    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = RootCauseService(
            admin_session, tid, None, provider=_build_mock_provider()
        )
        result = await service.generate(
            primary_category="kargo", perspective_code="__unmatched__"
        )
        assert result["review_count"] == 13
        assert result["perspective_code"] == "__unmatched__"


@pytest.mark.asyncio
async def test_service_is_rls_isolated(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    manual_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """Komşu kurumun 20 yorumu A kurumunun kovasına sızmamalı — A'da
    yalnız 4 satır var, eşik altında kalıp 400'e düşmeli."""
    del fake_redis_client
    _user_a, tid_a, _pw_a = semi_auto_tenant
    _user_b, tid_b, _pw_b = manual_tenant
    await mock_gemini_credential(tid_a, "fake-key", priority=0)
    await _seed_reviews(admin_session, tenant_id=tid_a, count=4)
    await _seed_reviews(admin_session, tenant_id=tid_b, count=20)

    async with admin_session.begin():
        await _bind_tenant(admin_session, tid_a)
        service = RootCauseService(
            admin_session, tid_a, None, provider=_build_mock_provider()
        )
        with pytest.raises(NotEnoughReviewsError):
            await service.generate(
                primary_category="kargo",
                perspective_code="order_status_wrong",
            )


# ---------------------------------------------------------------------------
# Route layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_404_when_never_generated(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        _ENDPOINT,
        params={
            "primary_category": "kargo",
            "perspective_code": "order_status_wrong",
        },
        headers=_auth(token),
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_get_returns_persisted_analysis(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        admin_session.add(
            RootCauseAnalysis(
                tenant_id=tid,
                primary_category_code="kargo",
                perspective_code="order_status_wrong",
                date_from=None,
                date_to=None,
                review_count=42,
                model_provider="gemini",
                model_name="gemini-3-flash-preview",
                payload=_payload(),
                generated_by_user_id=None,
            )
        )
        await admin_session.flush()

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        _ENDPOINT,
        params={
            "primary_category": "kargo",
            "perspective_code": "order_status_wrong",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review_count"] == 42
    assert body["payload"]["root_causes"][0]["share_estimate_pct"] == 62


@pytest.mark.asyncio
async def test_post_without_credentials_returns_412(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anahtar yok → 412 Precondition Failed; frontend ayarlar
    CTA'sını gösterir."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    from imga_api.services import root_cause_service

    monkeypatch.setattr(
        root_cause_service.RootCauseService,
        "generate",
        AsyncMock(side_effect=NoCredentialsError("no keys")),
    )
    r = batch_client.post(
        _ENDPOINT,
        headers=_auth(token),
        json={
            "primary_category": "kargo",
            "perspective_code": "order_status_wrong",
        },
    )
    assert r.status_code == 412, r.text


@pytest.mark.asyncio
async def test_post_below_minimum_reviews_returns_400(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
) -> None:
    """Gerçek servis yolu: kovada 3 yorum var → 400 + Türkçe detay."""
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)
    await _seed_reviews(admin_session, tenant_id=tid, count=3)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        _ENDPOINT,
        headers=_auth(token),
        json={
            "primary_category": "kargo",
            "perspective_code": "order_status_wrong",
        },
    )
    assert r.status_code == 400, r.text
    assert "yeterli yorum yok" in r.json()["detail"]


@pytest.mark.asyncio
async def test_post_invalid_primary_category_returns_422(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        _ENDPOINT,
        headers=_auth(token),
        json={
            "primary_category": "kargo_lojistik",
            "perspective_code": "order_status_wrong",
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_post_viewer_forbidden_analyst_allowed(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Okuma her üyeye açık; ÜRETİM yalnız yönetici + analist."""
    from imga_db.models import UserTenantRole

    from imga_api.services import AuditService, UserService, root_cause_service

    _admin, tid, _pw = semi_auto_tenant
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)

    viewer_pw = "Viewer-Password-123!"
    viewer_email = f"viewer-{uuid4().hex[:8]}@example.com"
    analyst_pw = "Analyst-Password-123!"
    analyst_email = f"analyst-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=viewer_email, password=viewer_pw, full_name="RC Viewer"
        )
        await usvc.attach_to_tenant(
            user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER
        )
        analyst = await usvc.create(
            email=analyst_email, password=analyst_pw, full_name="RC Analyst"
        )
        await usvc.attach_to_tenant(
            user_id=analyst.id, tenant_id=tid, role=UserTenantRole.ANALYST
        )
        viewer_id, analyst_id = viewer.id, analyst.id

    try:
        body = {
            "primary_category": "kargo",
            "perspective_code": "order_status_wrong",
        }
        viewer_token = login_token(batch_client, viewer_email, viewer_pw, tid)
        r = batch_client.post(
            _ENDPOINT, headers=_auth(viewer_token), json=body
        )
        assert r.status_code == 403, r.text

        monkeypatch.setattr(
            root_cause_service.RootCauseService,
            "generate",
            AsyncMock(
                return_value={
                    "id": str(uuid4()),
                    "primary_category_code": "kargo",
                    "perspective_code": "order_status_wrong",
                    "date_from": None,
                    "date_to": None,
                    "review_count": 25,
                    "model_provider": "gemini",
                    "model_name": "gemini-3-flash-preview",
                    "payload": _payload(),
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
        analyst_token = login_token(
            batch_client, analyst_email, analyst_pw, tid
        )
        r = batch_client.post(
            _ENDPOINT, headers=_auth(analyst_token), json=body
        )
        assert r.status_code == 200, r.text
        assert r.json()["review_count"] == 25
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": [str(viewer_id), str(analyst_id)]},
            )
