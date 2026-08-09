"""Sprint 13.1 — ``GET /tenants/me/analytics/category-drilldown``.

Bu dosyanın asıl işi TEK bir kuralı çivilemek:

    Drill-down sayımları YALNIZ review kolonlarından kurulur —
    ``WHERE primary_category = :x GROUP BY company_perspective_code``.

Tarihsel perspektif kodları ana kategoriden bağımsız bir keyword
sezgiseliyle atandığı için bir yorum ``primary=faturalama`` +
``perspective=shipment_not_arrived`` olabilir. Eğer endpoint
taksonominin ``primary_category_code`` eşlemesine göre gruplasaydı, o
satır "kargo" drill-down'ında görünür ama tıklandığında açılan
``/reviews?primary_categories=kargo&perspective_codes=
shipment_not_arrived`` listesi BOŞ dönerdi. Testler tam olarak bu
uyumsuz satırı kurup doğru kovada çıktığını doğruluyor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token

_ENDPOINT = "/tenants/me/analytics/category-drilldown"


async def _seed_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    primary_category: str,
    perspective_code: str | None,
    sentiment: str = "NEGATIF",
    score: float = -0.7,
    when: datetime | None = None,
) -> UUID:
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        review = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label=sentiment,
            sentiment_score=score,
            primary_category=primary_category,
            primary_confidence=0.8,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            analyzed_at=when or datetime.now(UTC),
            review_date=when or datetime.now(UTC),
            company_perspective_code=perspective_code,
        )
        admin_session.add(review)
        await admin_session.flush()
        rid = review.id
        admin_session.expunge(review)
    return rid


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_buckets_come_from_review_columns_not_taxonomy_mapping(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """``shipment_not_arrived`` taksonomide 'kargo'ya eşlenmiş; ama
    primary_category='faturalama' olan bir yorum FATURALAMA
    drill-down'ında çıkmalı, kargo'da DEĞİL."""
    user, tid, pw = semi_auto_tenant

    # Uyumsuz satır: primary=faturalama, perspektif=kargo alt kategorisi.
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Faturam yanlış ama kargom da gelmedi",
        primary_category="faturalama",
        perspective_code="shipment_not_arrived",
    )
    # Uyumlu satır: primary=kargo.
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Kargom hâlâ ulaşmadı",
        primary_category="kargo",
        perspective_code="shipment_not_arrived",
    )

    token = login_token(batch_client, user.email, pw, tid)

    kargo = batch_client.get(
        _ENDPOINT, params={"primary_category": "kargo"}, headers=_auth(token)
    )
    assert kargo.status_code == 200, kargo.text
    kargo_body = kargo.json()
    assert kargo_body["total"] == 1
    kargo_rows = {r["code"]: r for r in kargo_body["data"]}
    assert kargo_rows["shipment_not_arrived"]["total"] == 1

    faturalama = batch_client.get(
        _ENDPOINT,
        params={"primary_category": "faturalama"},
        headers=_auth(token),
    )
    assert faturalama.status_code == 200, faturalama.text
    fatura_body = faturalama.json()
    assert fatura_body["total"] == 1
    fatura_rows = {r["code"]: r for r in fatura_body["data"]}
    # Eşleme değil, review kolonu belirledi.
    assert fatura_rows["shipment_not_arrived"]["total"] == 1


@pytest.mark.asyncio
async def test_unmatched_bucket_collects_null_perspective_rows(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """NULL perspektifli satırlar düşürülmez; ``__unmatched__``
    kovasında toplanır (aynı sentinel /reviews filtresinde geçerli)."""
    user, tid, pw = semi_auto_tenant

    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Kargo hakkında genel bir not",
        primary_category="kargo",
        perspective_code=None,
    )
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Başka bir kargo notu",
        primary_category="kargo",
        perspective_code=None,
    )
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Kargom gelmedi",
        primary_category="kargo",
        perspective_code="shipment_not_arrived",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        _ENDPOINT, params={"primary_category": "kargo"}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    rows = {x["code"]: x for x in body["data"]}
    assert rows["__unmatched__"]["total"] == 2
    # Eşleşmeyen kovanın etiketi kodun kendisine düşer (taksonomi
    # satırı yok) — UI onu kendi metniyle değiştiriyor.
    assert rows["__unmatched__"]["label_tr"] == "__unmatched__"
    assert rows["shipment_not_arrived"]["total"] == 1


@pytest.mark.asyncio
async def test_negative_counts_and_shares(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant

    for i in range(3):
        await _seed_review(
            admin_session,
            tenant_id=tid,
            text_value=f"Kargom gelmedi {i}",
            primary_category="kargo",
            perspective_code="shipment_not_arrived",
            sentiment="NEGATIF",
            score=-0.8,
        )
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Kargo çok hızlıydı teşekkürler",
        primary_category="kargo",
        perspective_code="shipment_not_arrived",
        sentiment="POZITIF",
        score=0.9,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        _ENDPOINT, params={"primary_category": "kargo"}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4
    assert body["negative_total"] == 3
    row = next(x for x in body["data"] if x["code"] == "shipment_not_arrived")
    assert row["total"] == 4
    assert row["negative_count"] == 3
    assert row["negative_share"] == pytest.approx(75.0)
    assert row["share"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_invalid_primary_category_is_422(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        _ENDPOINT,
        params={"primary_category": "kargo_lojistik"},
        headers=_auth(token),
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_drilldown_is_rls_isolated_per_tenant(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    manual_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Komşu kurumun yorumları sayıma girmemeli."""
    user_a, tid_a, pw_a = semi_auto_tenant
    _user_b, tid_b, _pw_b = manual_tenant

    await _seed_review(
        admin_session,
        tenant_id=tid_a,
        text_value="A kurumunun kargo yorumu",
        primary_category="kargo",
        perspective_code="shipment_not_arrived",
    )
    for i in range(4):
        await _seed_review(
            admin_session,
            tenant_id=tid_b,
            text_value=f"B kurumunun kargo yorumu {i}",
            primary_category="kargo",
            perspective_code="shipment_not_arrived",
        )

    token = login_token(batch_client, user_a.email, pw_a, tid_a)
    r = batch_client.get(
        _ENDPOINT, params={"primary_category": "kargo"}, headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
