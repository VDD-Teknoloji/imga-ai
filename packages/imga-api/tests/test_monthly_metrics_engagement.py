"""Aylık işlem adedi + katılım oranı (katılım = yorum / işlem).

Kapsam:

  1. Upsert + ay normalizasyonu (ayın 17'si gönderilse de 1'i yazılır)
  2. Aynı ay ikinci kez PUT edilirse yeni satır değil güncelleme
  3. Katılım matematiği — yorumlar ``review_date`` ekseninde aylara
     dağıtılır, oran = yorum / işlem * 100
  4. Bant kenarları: eşiğin tam üstü üst banda düşer; bant satırı
     yoksa varsayılanlar; işlem adedi yoksa/0 ise oran ``null``
  5. RLS izolasyonu — B kurumu A'nın satırlarını göremez
  6. Yetki matrisi: viewer yazamaz (403), tenant_admin admin bant
     ucuna giremez (403), süper yönetici girer (200), token yoksa 401
  7. Bant doğrulaması 422: azalan min_pct, boş etiket, 0'dan
     başlamayan liste

``review_date`` NOT NULL (migration 0038) — seed'ler değeri açıkça
yazar; ``ReviewFactory`` bu kolonu henüz varsayılan olarak üretmiyor.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db import create_engine, create_session_factory
from imga_db.models import Review, ReviewDecision, User, UserTenantRole
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from imga_api.main import app
from imga_api.security import hash_password
from imga_api.services import AuditService, TenantService, UserService
from imga_api.settings import Settings

_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")
_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")
ADMIN_URL = f"postgresql+asyncpg://imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"
APP_URL = f"postgresql+asyncpg://imga_app:imga_app_password@{_HOST}:{_PORT}/imga"
OWNER_URL = f"postgresql+asyncpg://imga_owner:imga_dev_password@{_HOST}:{_PORT}/imga"

SUPER_ADMIN_PASSWORD = "test-super-admin-pwd-32-chars-min"

METRICS_URL = "/tenants/me/monthly-metrics"
ENGAGEMENT_URL = "/tenants/me/engagement"


@pytest.fixture(autouse=True)
def _set_test_env() -> None:
    os.environ["DATABASE_URL"] = APP_URL
    os.environ["DATABASE_URL_ADMIN"] = ADMIN_URL
    os.environ["DATABASE_URL_OWNER"] = OWNER_URL
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-32-bytes-min-padding-xyz"


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine("admin")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def admin_session(admin_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = create_session_factory(admin_engine)
    async with factory() as session:
        yield session


async def _seed_user(
    admin_session: AsyncSession,
    role: UserTenantRole,
) -> tuple[User, UUID, str]:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"eng-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(name="Eng Co", slug=f"eng-{uuid4().hex[:8]}")
        user = await usvc.create(email=email, password=plain, full_name="Eng User")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant.id, role=role
        )
        return user, tenant.id, plain


async def _cleanup(
    admin_session: AsyncSession, user_id: UUID, tenant_id: UUID
) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM reviews WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)}
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
        )


@pytest_asyncio.fixture
async def tenant_admin(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_user(admin_session, UserTenantRole.TENANT_ADMIN)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def other_tenant_admin(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_user(admin_session, UserTenantRole.TENANT_ADMIN)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def analyst_user(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_user(admin_session, UserTenantRole.ANALYST)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def viewer_user(
    admin_session: AsyncSession,
) -> AsyncIterator[tuple[User, UUID, str]]:
    user, tid, pw = await _seed_user(admin_session, UserTenantRole.VIEWER)
    yield user, tid, pw
    await _cleanup(admin_session, user.id, tid)


@pytest_asyncio.fixture
async def super_admin(admin_session: AsyncSession) -> AsyncIterator[User]:
    """Migration 0001'in seed ettiği admin@imga.ai satırının parolasını
    testin sahip olduğu bir değerle yeniden yazar."""
    async with admin_session.begin():
        await admin_session.execute(
            text(
                "UPDATE users SET password_hash = :pw, is_active = true "
                "WHERE email = 'admin@imga.ai'"
            ),
            {"pw": hash_password(SUPER_ADMIN_PASSWORD)},
        )
        user = (
            await admin_session.execute(
                select(User).where(User.email == "admin@imga.ai")
            )
        ).scalar_one()
    yield user


@pytest.fixture
def client() -> Iterator[TestClient]:
    @asynccontextmanager
    async def _test_lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = Settings.from_env()
        application.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)
        yield

    original = app.router.lifespan_context
    app.router.lifespan_context = _test_lifespan
    for attr in ("admin_db_engine", "app_db_engine",
                 "admin_db_engine_factory", "app_db_engine_factory"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.router.lifespan_context = original
        for attr in ("admin_db_engine", "app_db_engine",
                     "admin_db_engine_factory", "app_db_engine_factory",
                     "tenant_config_cache"):
            if hasattr(app.state, attr):
                delattr(app.state, attr)


def _login(
    client: TestClient,
    email: str,
    password: str,
    tenant_id: UUID | None = None,
) -> str:
    payload: dict[str, str] = {"email": email, "password": password}
    if tenant_id is not None:
        payload["active_tenant_id"] = str(tenant_id)
    r = client.post("/auth/login", json=payload)
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def _seed_reviews(
    admin_session: AsyncSession,
    tenant_id: UUID,
    *,
    review_date: datetime,
    count: int,
) -> None:
    """``review_date`` açıkça yazılır — kolon NOT NULL (0038) ve
    ``ReviewFactory``de varsayılanı yok."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        for i in range(count):
            body = f"katılım testi yorumu {uuid4().hex[:8]} {i}"
            admin_session.add(
                Review(
                    tenant_id=tenant_id,
                    text=body,
                    text_hash=review_text_hash(body),
                    sentiment_label="NÖTR",
                    sentiment_score=0.0,
                    primary_category="diğer",
                    primary_confidence=0.5,
                    automation_mode="semi_auto",
                    decision=ReviewDecision.SKIPPED_THRESHOLD,
                    decision_reason=None,
                    analyzed_at=datetime.now(UTC),
                    review_date=review_date,
                )
            )
        await admin_session.flush()


def _row_for(body: dict[str, object], month: str) -> dict[str, object]:
    rows = [r for r in body["rows"] if r["period_month"] == month]  # type: ignore[union-attr]
    assert rows, f"{month} satırı yok: {body}"
    return dict(rows[0])


# --- 1. upsert + ay normalizasyonu --------------------------------------


def test_upsert_normalizes_period_month_to_first_of_month(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    r = client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-05-17", "transaction_count": 100000},
    )
    assert r.status_code == 200, r.text
    assert r.json()["period_month"] == "2026-05-01"

    listed = client.get(METRICS_URL, headers=headers)
    assert listed.status_code == 200
    assert [m["period_month"] for m in listed.json()] == ["2026-05-01"]


# --- 2. ay başına tek satır ---------------------------------------------


def test_second_put_updates_instead_of_duplicating(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    first = client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-05-01", "transaction_count": 100000},
    )
    assert first.status_code == 200, first.text
    second = client.put(
        METRICS_URL,
        headers=headers,
        json={
            "period_month": "2026-05-01",
            "transaction_count": 120000,
            "notes": "revize",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["transaction_count"] == 120000
    assert second.json()["notes"] == "revize"

    listed = client.get(METRICS_URL, headers=headers).json()
    assert len(listed) == 1


def test_delete_month_removes_row(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-05-01", "transaction_count": 5},
    )
    r = client.delete(f"{METRICS_URL}/2026-05-01", headers=headers)
    assert r.status_code == 204, r.text
    assert client.get(METRICS_URL, headers=headers).json() == []

    # Normalizasyon silmede de geçerli: ayın ortası da aynı satırı bulur.
    client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-06-01", "transaction_count": 5},
    )
    r2 = client.delete(f"{METRICS_URL}/2026-06-14", headers=headers)
    assert r2.status_code == 204, r2.text


def test_delete_unknown_month_returns_404(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    r = client.delete(f"{METRICS_URL}/2020-01-01", headers=headers)
    assert r.status_code == 404, r.text


# --- 3. katılım matematiği ----------------------------------------------


@pytest.mark.asyncio
async def test_engagement_math_buckets_on_review_date(
    client: TestClient,
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    """İki farklı aya dağılmış yorumlar + iki aylık işlem adedi.
    Yorumların hepsi bugün eklendi ama ``review_date`` geçmiş aylara
    işaret ediyor — bucket ``created_at`` olsaydı ikisi de tek aya
    yığılırdı."""
    user, tid, pw = tenant_admin
    today = datetime.now(UTC)
    this_month = date(today.year, today.month, 1)
    previous_month = (
        date(this_month.year - 1, 12, 1)
        if this_month.month == 1
        else date(this_month.year, this_month.month - 1, 1)
    )
    # 5 yorum / 100 işlem = %5 (en üst bant); 1 yorum / 100 işlem = %1.
    await _seed_reviews(
        admin_session,
        tid,
        review_date=datetime(
            this_month.year, this_month.month, 1, 12, 0, tzinfo=UTC
        ),
        count=5,
    )
    await _seed_reviews(
        admin_session,
        tid,
        review_date=datetime(
            previous_month.year, previous_month.month, 15, 12, 0, tzinfo=UTC
        ),
        count=1,
    )

    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    for month in (this_month, previous_month):
        r = client.put(
            METRICS_URL,
            headers=headers,
            json={
                "period_month": month.isoformat(),
                "transaction_count": 100,
            },
        )
        assert r.status_code == 200, r.text

    body = client.get(ENGAGEMENT_URL, headers=headers).json()
    assert len(body["rows"]) == 12, "varsayılan pencere son 12 ay"
    # En yeni ay en üstte.
    assert body["rows"][0]["period_month"] == this_month.isoformat()

    current = _row_for(body, this_month.isoformat())
    assert current["review_count"] == 5
    assert current["transaction_count"] == 100
    assert current["engagement_pct"] == 5.0
    assert current["band_label"] == "Çok İyi"
    assert current["band_index"] == 3

    previous = _row_for(body, previous_month.isoformat())
    assert previous["review_count"] == 1
    assert previous["engagement_pct"] == 1.0
    assert previous["band_label"] == "Kötü"


@pytest.mark.asyncio
async def test_month_with_reviews_but_no_transaction_count_has_null_pct(
    client: TestClient,
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    """İşlem adedi girilmemiş ay tabloda görünür ama oran boştur —
    UI bunu 'veri girin' çağrısına çevirir."""
    user, tid, pw = tenant_admin
    today = datetime.now(UTC)
    this_month = date(today.year, today.month, 1)
    await _seed_reviews(
        admin_session,
        tid,
        review_date=datetime(
            this_month.year, this_month.month, 1, 9, 0, tzinfo=UTC
        ),
        count=3,
    )
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    body = client.get(ENGAGEMENT_URL, headers=headers).json()
    row = _row_for(body, this_month.isoformat())
    assert row["review_count"] == 3
    assert row["transaction_count"] is None
    assert row["engagement_pct"] is None
    assert row["band_label"] is None
    assert row["band_index"] is None


def test_zero_transaction_count_yields_null_pct_not_error(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    """0 işlem girilirse bölme yapılmaz; boş hücre döner."""
    user, tid, pw = tenant_admin
    today = datetime.now(UTC)
    this_month = date(today.year, today.month, 1)
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    r = client.put(
        METRICS_URL,
        headers=headers,
        json={
            "period_month": this_month.isoformat(),
            "transaction_count": 0,
        },
    )
    assert r.status_code == 200, r.text
    body = client.get(ENGAGEMENT_URL, headers=headers).json()
    row = _row_for(body, this_month.isoformat())
    assert row["transaction_count"] == 0
    assert row["engagement_pct"] is None
    assert row["band_label"] is None


def test_negative_transaction_count_rejected(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    r = client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-05-01", "transaction_count": -1},
    )
    assert r.status_code == 422, r.text


# --- 4. bant kenarları ---------------------------------------------------


def test_default_bands_returned_when_tenant_has_no_settings_row(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    body = client.get(ENGAGEMENT_URL, headers=headers).json()
    assert [b["label"] for b in body["bands"]] == [
        "Çok Kötü",
        "Kötü",
        "Orta",
        "Çok İyi",
    ]
    assert [b["min_pct"] for b in body["bands"]] == [0.0, 1.0, 2.0, 5.0]


@pytest.mark.asyncio
async def test_pct_exactly_at_threshold_lands_in_higher_band(
    client: TestClient,
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    """2 yorum / 100 işlem = tam %2 — 'Orta' bandının alt sınırı.
    Sınırdaki değer üst banda düşer, alt bantta kalmaz."""
    user, tid, pw = tenant_admin
    today = datetime.now(UTC)
    this_month = date(today.year, today.month, 1)
    await _seed_reviews(
        admin_session,
        tid,
        review_date=datetime(
            this_month.year, this_month.month, 2, 10, 0, tzinfo=UTC
        ),
        count=2,
    )
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": this_month.isoformat(), "transaction_count": 100},
    )
    body = client.get(ENGAGEMENT_URL, headers=headers).json()
    row = _row_for(body, this_month.isoformat())
    assert row["engagement_pct"] == 2.0
    assert row["band_label"] == "Orta"
    assert row["band_index"] == 2


@pytest.mark.asyncio
async def test_custom_bands_override_defaults_in_engagement_response(
    client: TestClient,
    admin_session: AsyncSession,
    super_admin: User,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    today = datetime.now(UTC)
    this_month = date(today.year, today.month, 1)
    await _seed_reviews(
        admin_session,
        tid,
        review_date=datetime(
            this_month.year, this_month.month, 3, 10, 0, tzinfo=UTC
        ),
        count=10,
    )
    super_headers = {
        "Authorization": (
            f"Bearer {_login(client, 'admin@imga.ai', SUPER_ADMIN_PASSWORD)}"
        )
    }
    put = client.put(
        f"/admin/tenants/{tid}/engagement-bands",
        headers=super_headers,
        json={
            "bands": [
                {"min_pct": 0, "label": "Yetersiz"},
                {"min_pct": 10, "label": "Sektör Lideri"},
            ]
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["is_default"] is False

    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": this_month.isoformat(), "transaction_count": 100},
    )
    body = client.get(ENGAGEMENT_URL, headers=headers).json()
    assert [b["label"] for b in body["bands"]] == ["Yetersiz", "Sektör Lideri"]
    row = _row_for(body, this_month.isoformat())
    assert row["engagement_pct"] == 10.0
    assert row["band_label"] == "Sektör Lideri"
    assert row["band_index"] == 1


# --- 5. RLS izolasyonu ---------------------------------------------------


def test_tenant_b_cannot_see_tenant_a_monthly_metrics(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
    other_tenant_admin: tuple[User, UUID, str],
) -> None:
    user_a, tid_a, pw_a = tenant_admin
    user_b, tid_b, pw_b = other_tenant_admin
    headers_a = {
        "Authorization": f"Bearer {_login(client, user_a.email, pw_a, tid_a)}"
    }
    headers_b = {
        "Authorization": f"Bearer {_login(client, user_b.email, pw_b, tid_b)}"
    }
    r = client.put(
        METRICS_URL,
        headers=headers_a,
        json={"period_month": "2026-05-01", "transaction_count": 77777},
    )
    assert r.status_code == 200, r.text

    listed_b = client.get(METRICS_URL, headers=headers_b).json()
    assert listed_b == []
    counts_b = [
        row["transaction_count"]
        for row in client.get(ENGAGEMENT_URL, headers=headers_b).json()["rows"]
    ]
    assert all(c is None for c in counts_b)


@pytest.mark.asyncio
async def test_tenant_b_review_counts_do_not_leak_into_tenant_a(
    client: TestClient,
    admin_session: AsyncSession,
    tenant_admin: tuple[User, UUID, str],
    other_tenant_admin: tuple[User, UUID, str],
) -> None:
    user_a, tid_a, pw_a = tenant_admin
    _user_b, tid_b, _pw_b = other_tenant_admin
    today = datetime.now(UTC)
    this_month = date(today.year, today.month, 1)
    await _seed_reviews(
        admin_session,
        tid_b,
        review_date=datetime(
            this_month.year, this_month.month, 4, 10, 0, tzinfo=UTC
        ),
        count=9,
    )
    headers_a = {
        "Authorization": f"Bearer {_login(client, user_a.email, pw_a, tid_a)}"
    }
    body = client.get(ENGAGEMENT_URL, headers=headers_a).json()
    assert all(row["review_count"] == 0 for row in body["rows"])


# --- 6. yetki matrisi ----------------------------------------------------


def test_viewer_can_read_but_cannot_write(
    client: TestClient,
    viewer_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = viewer_user
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    assert client.get(METRICS_URL, headers=headers).status_code == 200
    assert client.get(ENGAGEMENT_URL, headers=headers).status_code == 200

    write = client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-05-01", "transaction_count": 10},
    )
    assert write.status_code == 403, write.text
    delete = client.delete(f"{METRICS_URL}/2026-05-01", headers=headers)
    assert delete.status_code == 403, delete.text


def test_analyst_can_write(
    client: TestClient,
    analyst_user: tuple[User, UUID, str],
) -> None:
    user, tid, pw = analyst_user
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    r = client.put(
        METRICS_URL,
        headers=headers,
        json={"period_month": "2026-05-01", "transaction_count": 42},
    )
    assert r.status_code == 200, r.text


def test_unauthenticated_requests_are_401(client: TestClient) -> None:
    assert client.get(METRICS_URL).status_code == 401
    assert client.get(ENGAGEMENT_URL).status_code == 401
    assert (
        client.get(f"/admin/tenants/{uuid4()}/engagement-bands").status_code
        == 401
    )


def test_tenant_admin_cannot_touch_admin_bands_endpoints(
    client: TestClient,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    user, tid, pw = tenant_admin
    headers = {"Authorization": f"Bearer {_login(client, user.email, pw, tid)}"}
    read = client.get(f"/admin/tenants/{tid}/engagement-bands", headers=headers)
    assert read.status_code == 403, read.text
    write = client.put(
        f"/admin/tenants/{tid}/engagement-bands",
        headers=headers,
        json={"bands": [{"min_pct": 0, "label": "X"}]},
    )
    assert write.status_code == 403, write.text


def test_super_admin_reads_defaults_then_writes_bands(
    client: TestClient,
    super_admin: User,
    tenant_admin: tuple[User, UUID, str],
) -> None:
    _user, tid, _pw = tenant_admin
    headers = {
        "Authorization": (
            f"Bearer {_login(client, 'admin@imga.ai', SUPER_ADMIN_PASSWORD)}"
        )
    }
    read = client.get(f"/admin/tenants/{tid}/engagement-bands", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["is_default"] is True
    assert len(read.json()["bands"]) == 4

    write = client.put(
        f"/admin/tenants/{tid}/engagement-bands",
        headers=headers,
        json={
            "bands": [
                {"min_pct": 0, "label": "Zayıf"},
                {"min_pct": 3, "label": "Güçlü"},
            ]
        },
    )
    assert write.status_code == 200, write.text
    again = client.get(f"/admin/tenants/{tid}/engagement-bands", headers=headers)
    assert again.json()["is_default"] is False
    assert [b["label"] for b in again.json()["bands"]] == ["Zayıf", "Güçlü"]


def test_admin_bands_unknown_tenant_is_404(
    client: TestClient,
    super_admin: User,
) -> None:
    headers = {
        "Authorization": (
            f"Bearer {_login(client, 'admin@imga.ai', SUPER_ADMIN_PASSWORD)}"
        )
    }
    ghost = uuid4()
    assert (
        client.get(
            f"/admin/tenants/{ghost}/engagement-bands", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/admin/tenants/{ghost}/engagement-bands",
            headers=headers,
            json={"bands": [{"min_pct": 0, "label": "X"}]},
        ).status_code
        == 404
    )


# --- 7. bant doğrulaması -------------------------------------------------


@pytest.mark.parametrize(
    "bands",
    [
        # azalan min_pct
        [{"min_pct": 5, "label": "İyi"}, {"min_pct": 1, "label": "Kötü"}],
        # tekrar eden min_pct
        [{"min_pct": 0, "label": "A"}, {"min_pct": 0, "label": "B"}],
        # 0'dan başlamıyor
        [{"min_pct": 1, "label": "A"}, {"min_pct": 2, "label": "B"}],
        # boş etiket
        [{"min_pct": 0, "label": ""}],
        # boş liste
        [],
        # 8 banttan fazla
        [{"min_pct": i, "label": f"B{i}"} for i in range(9)],
    ],
)
def test_invalid_band_payloads_are_422(
    client: TestClient,
    super_admin: User,
    tenant_admin: tuple[User, UUID, str],
    bands: list[dict[str, object]],
) -> None:
    _user, tid, _pw = tenant_admin
    headers = {
        "Authorization": (
            f"Bearer {_login(client, 'admin@imga.ai', SUPER_ADMIN_PASSWORD)}"
        )
    }
    r = client.put(
        f"/admin/tenants/{tid}/engagement-bands",
        headers=headers,
        json={"bands": bands},
    )
    assert r.status_code == 422, r.text
