"""Sprint 10.0 — /tenants/me/executive/overview regression testleri.

C-level dashboard'un tek-bakış endpoint'i. İki kontrat:

  * Boş tenant: sentiment sıfırları + tüm snapshot'lar null +
    voice_of_customer boş liste. Frontend bu durumda her blok için
    "oluşturun" CTA'sı gösterir; null'lar 500'e dönüşmemeli.
  * Dolu tenant: duygu sayıları doğru gruplanır, en negatif kategori
    'belirsiz' HARİÇ hesaplanır, Müşterinin Sesi 2 negatif + 1
    pozitif gerçek alıntı döner (kısa yorumlar elenir), son SWOT /
    OKR / briefing snapshot'ları payload şekilleriyle gelir.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    ExecutiveBriefing,
    Review,
    ReviewDecision,
    StrategicReport,
    User,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


async def _seed_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment_label: str,
    sentiment_score: float,
    primary_category: str = "kargo",
    created_at: datetime | None = None,
) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        kwargs: dict[str, object] = {
            "tenant_id": tenant_id,
            "text": text_value,
            "text_hash": review_text_hash(text_value),
            "sentiment_label": sentiment_label,
            "sentiment_score": sentiment_score,
            "primary_category": primary_category,
            "primary_confidence": 0.8,
            "automation_mode": "semi_auto",
            "decision": ReviewDecision.SKIPPED_THRESHOLD,
            "decision_reason": None,
            "ticket_id": None,
            "submitted_by_user_id": None,
            "batch_job_id": None,
            "analyzed_at": datetime.now(UTC),
        }
        if created_at is not None:
            kwargs["created_at"] = created_at
        row = Review(**kwargs)
        admin_session.add(row)
        await admin_session.flush()
        admin_session.expunge(row)


@pytest.mark.asyncio
async def test_overview_empty_tenant_returns_nulls_and_zeros(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/executive/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sentiment"] == {
        "POZITIF": 0, "NEGATIF": 0, "NÖTR": 0, "total": 0,
    }
    assert body["top_problems"] == []
    assert body["trend"] is None
    assert body["nps_score"] is None
    assert body["voice_of_customer"] == []
    assert body["latest_briefing"] is None
    assert body["latest_swot"] is None
    assert body["latest_okr"] is None
    assert body["last_data_at"] is None


@pytest.mark.asyncio
async def test_overview_populated_returns_full_payload(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant

    # --- yorumlar: 3 negatif (2 uzun kargo + 1 KISA — elenmeli),
    # 2 pozitif uzun, 1 nötr. 'belirsiz' kategorili 4 negatif satır —
    # top_negative_category 'belirsiz'i ATLAMALI, kargo dönmeli.
    long_neg_1 = (
        "Kargom üç gündür gelmedi, müşteri hizmetlerine kimse "
        "cevap vermiyor, bu nasıl bir hizmet anlayışı gerçekten."
    )
    long_neg_2 = (
        "Teslimat çok gecikti ve paket hasarlı geldi; iade süreci "
        "de bir o kadar yorucu, kimse sorumluluk almıyor."
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value=long_neg_1,
        sentiment_label="NEGATIF", sentiment_score=-0.95,
        primary_category="kargo",
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value=long_neg_2,
        sentiment_label="NEGATIF", sentiment_score=-0.9,
        primary_category="kargo",
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="çok kötü",
        sentiment_label="NEGATIF", sentiment_score=-0.99,
        primary_category="kargo",
    )
    for i in range(4):
        await _seed_review(
            admin_session, tenant_id=tid,
            text_value=f"anlaşılmaz kısa metin numara {i} olsun yeter",
            sentiment_label="NEGATIF", sentiment_score=-0.5,
            primary_category="belirsiz",
        )
    await _seed_review(
        admin_session, tenant_id=tid,
        text_value=(
            "Ürün kalitesi beklentimin çok üzerinde çıktı, herkese "
            "gönül rahatlığıyla tavsiye ederim, teşekkürler."
        ),
        sentiment_label="POZITIF", sentiment_score=0.95,
        primary_category="urun-kalitesi",
    )
    await _seed_review(
        admin_session, tenant_id=tid,
        text_value=(
            "Sipariş süreci sorunsuzdu ve destek ekibi sorularıma "
            "hızla dönüş yaptı, gayet memnun kaldım."
        ),
        sentiment_label="POZITIF", sentiment_score=0.8,
        primary_category="musteri-hizmetleri",
    )
    await _seed_review(
        admin_session, tenant_id=tid,
        text_value="Fiyat performans açısından ortalama bir deneyimdi diyebilirim.",
        sentiment_label="NÖTR", sentiment_score=0.0,
        primary_category="fiyatlandirma",
    )

    # --- son SWOT + OKR + briefing
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        swot = StrategicReport(
            tenant_id=tid,
            report_type="swot",
            input_stats={"total_reviews": 10},
            model_name="test-model",
            output_payload={
                "strengths": [
                    {"title": "Hızlı destek", "description": "d1", "evidence": "e1"},
                    {"title": "Ürün kalitesi", "description": "d2", "evidence": "e2"},
                    {"title": "Üçüncü güç", "description": "d3", "evidence": "e3"},
                ],
                "weaknesses": [
                    {"title": "Kargo gecikmesi", "description": "w1", "evidence": "e"},
                ],
                "opportunities": [],
                "threats": [],
                "strategic_recommendations": [
                    {
                        "title": "Orta öncelik",
                        "description": "rd0",
                        "priority": "orta",
                        "estimated_impact": "orta",
                    },
                    {
                        "title": "Kargo SLA'yı 2 güne indir",
                        "description": "rd1",
                        "priority": "yüksek",
                        "estimated_impact": "yüksek",
                    },
                ],
            },
        )
        admin_session.add(swot)
        okr = StrategicReport(
            tenant_id=tid,
            report_type="okr",
            input_stats={},
            model_name="test-model",
            output_payload={
                "objectives": [
                    {
                        "objective": "Kargo memnuniyetini artır",
                        "rationale": "r",
                        "key_results": [
                            {
                                "text": "Ortalama teslim süresi 2 güne insin",
                                "metric": "avg_delivery_days",
                                "baseline": "4",
                                "target": "2",
                            },
                        ],
                    },
                ],
            },
        )
        admin_session.add(okr)
        briefing = ExecutiveBriefing(
            tenant_id=tid,
            period="month",
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 31),
            headline="Kargo şikayetleri NPS'i aşağı çekiyor",
            kpi_changes=[],
            critical_insights=["İçgörü 1", "İçgörü 2", "İçgörü 3", "İçgörü 4"],
            top_actions=[],
            input_stats={},
            model_name="test-model",
        )
        admin_session.add(briefing)
        await admin_session.flush()

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/executive/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Duygu toplamları: 7 negatif (3 kargo + 4 belirsiz), 2 pozitif, 1 nötr.
    assert body["sentiment"]["NEGATIF"] == 7
    assert body["sentiment"]["POZITIF"] == 2
    assert body["sentiment"]["NÖTR"] == 1
    assert body["sentiment"]["total"] == 10

    # Trend: tüm yorumlar şimdi seed'lendi → önceki 30 günlük pencere
    # boş → trend iddia edilmez (None).
    assert body["trend"] is None

    # Ana Sorunlar: belirsiz 4 satırla önde AMA elenir → kargo (3)
    # tek satır olarak döner. share_pct paydası TÜM negatifler (7):
    # 3/7 ≈ %42.9. sample_text en sert ANLAMLI yorum — "çok kötü"
    # (-0.99) kısa olduğu için elenir, long_neg_1 (-0.95) seçilir.
    problems = body["top_problems"]
    assert len(problems) == 1
    assert problems[0]["code"] == "kargo"
    assert problems[0]["count"] == 3
    assert 42.0 <= problems[0]["share_pct"] <= 43.5
    assert problems[0]["sample_text"] is not None
    assert problems[0]["sample_text"].startswith("Kargom üç gündür")

    # Müşterinin Sesi: 2 negatif + 1 pozitif; "çok kötü" (kısa) elenmiş
    # olmalı, en negatif UZUN yorumlar dönmeli.
    voice = body["voice_of_customer"]
    assert len(voice) == 3
    neg_quotes = [q for q in voice if q["sentiment_label"] == "NEGATIF"]
    pos_quotes = [q for q in voice if q["sentiment_label"] == "POZITIF"]
    assert len(neg_quotes) == 2
    assert len(pos_quotes) == 1
    assert all(len(q["text"]) >= 40 for q in voice), (
        "kısa yorumlar ('çok kötü') Müşterinin Sesi'ne sızmamalı"
    )
    assert pos_quotes[0]["text"].startswith("Ürün kalitesi beklentimin")

    # Son briefing: headline + max 3 insight.
    assert body["latest_briefing"] is not None
    assert body["latest_briefing"]["headline"].startswith("Kargo şikayetleri")
    assert len(body["latest_briefing"]["critical_insights"]) == 3

    # Son SWOT: 2 strength (3'ten kırpılmış), 1 weakness, yüksek
    # öncelikli tavsiye seçilmiş.
    swot_snap = body["latest_swot"]
    assert swot_snap is not None
    assert len(swot_snap["strengths"]) == 2
    assert len(swot_snap["weaknesses"]) == 1
    assert swot_snap["top_recommendation"]["title"] == "Kargo SLA'yı 2 güne indir"
    assert swot_snap["top_recommendation"]["priority"] == "yüksek"

    # Son OKR: 1 objective + key result alanları.
    okr_snap = body["latest_okr"]
    assert okr_snap is not None
    assert len(okr_snap["objectives"]) == 1
    kr = okr_snap["objectives"][0]["key_results"][0]
    assert kr["metric"] == "avg_delivery_days"
    assert kr["target"] == "2"

    # Son veri girişi: yorumlar az önce seed'lendi → son 24 saat içinde.
    assert body["last_data_at"] is not None
    last_data = datetime.fromisoformat(body["last_data_at"])
    assert (datetime.now(UTC) - last_data) < timedelta(hours=24)


@pytest.mark.asyncio
async def test_overview_trend_compares_30_day_windows(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Önceki pencere (30-60 gün önce): 1 pozitif / 2 yorum = %50.
    Güncel pencere (son 30 gün): 3 pozitif / 4 yorum = %75.
    delta = +25 puan."""
    user, tid, pw = semi_auto_tenant
    now = datetime.now(UTC)
    old = now - timedelta(days=45)

    await _seed_review(
        admin_session, tenant_id=tid,
        text_value="Eski dönemden memnun bir müşteri yorumu kaydı.",
        sentiment_label="POZITIF", sentiment_score=0.7,
        primary_category="urun-kalitesi", created_at=old,
    )
    await _seed_review(
        admin_session, tenant_id=tid,
        text_value="Eski dönemden memnuniyetsiz bir müşteri yorumu kaydı.",
        sentiment_label="NEGATIF", sentiment_score=-0.7,
        primary_category="kargo", created_at=old,
    )
    for i in range(3):
        await _seed_review(
            admin_session, tenant_id=tid,
            text_value=f"Yeni dönem pozitif müşteri yorumu numara {i}.",
            sentiment_label="POZITIF", sentiment_score=0.8,
            primary_category="urun-kalitesi",
        )
    await _seed_review(
        admin_session, tenant_id=tid,
        text_value="Yeni dönem negatif müşteri yorumu kaydı burada.",
        sentiment_label="NEGATIF", sentiment_score=-0.8,
        primary_category="kargo",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/executive/overview",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    trend = r.json()["trend"]
    assert trend is not None
    assert trend["previous_positive_pct"] == 50.0
    assert trend["current_positive_pct"] == 75.0
    assert trend["delta_points"] == 25.0
