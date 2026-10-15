"""Müşteri yolculuğu aşaması (migration 0052) — liste, özet, detay ve
analitik huni uçları.

Seeding ``test_reviews_summary.py`` ile aynı desen: RLS-bağlı
``set_config`` bloğu altında doğrudan ORM insert; ``journey_stage``
kolonu burada elle yazılır (LLM yolu ``tests-core`` tarafında ayrıca
test edilir: ``_parse_with_raw`` + ``journey_sink``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import JOURNEY_STAGES, review_text_hash
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


async def _insert(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    journey_stage: str | None,
    sentiment: str = "NÖTR",
    source: str | None = None,
) -> Review:
    now = datetime.now(UTC)
    review = Review(
        tenant_id=tenant_id,
        text=text_value,
        text_hash=review_text_hash(text_value),
        sentiment_label=sentiment,
        sentiment_score=-0.6 if sentiment == "NEGATIF" else 0.0,
        primary_category="kargo",
        primary_confidence=0.8,
        automation_mode="semi_auto",
        decision=ReviewDecision.SKIPPED_THRESHOLD,
        decision_reason=None,
        analyzed_at=now,
        review_date=now,
        source=source,
        journey_stage=journey_stage,
    )
    session.add(review)
    await session.flush()
    session.expunge(review)
    return review


async def _seed(session: AsyncSession, tenant_id: UUID) -> dict[str, UUID]:
    async with session.begin():
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows = {
            "teslimat_neg": await _insert(
                session,
                tenant_id=tenant_id,
                text_value="Kargom 5 gündür kımıldamıyor",
                journey_stage="teslimat",
                sentiment="NEGATIF",
                source="Twitter",
            ),
            "teslimat_ok": await _insert(
                session,
                tenant_id=tenant_id,
                text_value="Paketim bugün geldi, sağ olun",
                journey_stage="teslimat",
                sentiment="POZITIF",
                source="twitter ",
            ),
            "ayrilma": await _insert(
                session,
                tenant_id=tenant_id,
                text_value="Bir daha sizden almam, rakibe geçiyorum",
                journey_stage="ayrilma",
                sentiment="NEGATIF",
                source="Email",
            ),
            "none": await _insert(
                session,
                tenant_id=tenant_id,
                text_value="eski kayıt, aşaması yok",
                journey_stage=None,
                source="Email",
            ),
        }
    return {key: row.id for key, row in rows.items()}


@pytest.mark.asyncio
async def test_summary_list_and_detail_expose_journey_stage(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    ids = await _seed(admin_session, tid)
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    summary = batch_client.get("/tenants/me/reviews/summary", headers=headers).json()
    expected = dict.fromkeys(JOURNEY_STAGES, 0)
    expected.update({"teslimat": 2, "ayrilma": 1, "atanmamis": 1})
    assert summary["journey_stages"] == expected

    listed = batch_client.get(
        "/tenants/me/reviews", params={"journey_stages": "ayrilma"}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [str(ids["ayrilma"])]
    assert items[0]["journey_stage"] == "ayrilma"

    unassigned = batch_client.get(
        "/tenants/me/reviews", params={"journey_stages": "atanmamis"}, headers=headers
    ).json()["items"]
    assert [item["id"] for item in unassigned] == [str(ids["none"])]
    assert unassigned[0]["journey_stage"] is None

    mixed = batch_client.get(
        "/tenants/me/reviews",
        params={"journey_stages": "teslimat,atanmamis"},
        headers=headers,
    ).json()["items"]
    assert len(mixed) == 3

    detail = batch_client.get(f"/tenants/me/reviews/{ids['ayrilma']}", headers=headers).json()
    assert detail["journey_stage"] == "ayrilma"
    detail_none = batch_client.get(f"/tenants/me/reviews/{ids['none']}", headers=headers).json()
    assert detail_none["journey_stage"] is None


@pytest.mark.asyncio
async def test_journey_distribution_funnel_and_source_filter(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(admin_session, tid)
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = batch_client.get("/tenants/me/analytics/journey-distribution", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Huni sırası sabit ve her kod dolu (0 dahil); atanmamış paydaya girmez.
    assert [row["stage"] for row in body["stages"]] == list(JOURNEY_STAGES)
    by_stage = {row["stage"]: row for row in body["stages"]}
    assert by_stage["teslimat"] == {"stage": "teslimat", "total": 2, "negatif": 1}
    assert by_stage["ayrilma"]["total"] == 1 and by_stage["ayrilma"]["negatif"] == 1
    assert by_stage["kesif"]["total"] == 0
    assert body["total"] == 3
    assert body["atanmamis"] == {"total": 1, "negatif": 0}

    # Kaynak filtresi büyük/küçük harf ve boşluk katlar: "Twitter" ve
    # "twitter " aynı kovada; Email satırları dışarıda kalır.
    twitter = batch_client.get(
        "/tenants/me/analytics/journey-distribution",
        params={"sources": "twitter"},
        headers=headers,
    ).json()
    assert twitter["total"] == 2
    assert {row["stage"]: row["total"] for row in twitter["stages"]}["teslimat"] == 2
    assert twitter["atanmamis"]["total"] == 0
