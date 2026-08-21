"""Migration 0046 — ``/tenants/me/operations/*`` + ``/tenants/me/
fact-mappings`` route tests, plus the review-detail facts enrichment.

Requires live Postgres (RLS is a Postgres-only feature); part of the
server test-compose suite. Reviews + review_facts are seeded directly
via the ORM (``_seed``) to avoid coupling to the batch upload flow —
worker ingestion of facts is covered separately in
test_batch_quality.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, get_args
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import (
    Review,
    ReviewDecision,
    ReviewFact,
    User,
    UserTenantRole,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.routes.tenant_operations import FactFieldName
from imga_api.services import AuditService, UserService
from imga_api.services.fact_parsing import FACT_FIELDS
from tests.batch_helpers import login_token

_SET_TENANT_SQL = text("SELECT set_config('app.current_tenant_id', :t, true)")


async def _bind(admin_session: AsyncSession, tenant_id: UUID) -> None:
    await admin_session.execute(_SET_TENANT_SQL, {"t": str(tenant_id)})


async def _seed(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment: str = "NÖTR",
    score: float = 0.0,
    quality_flag: str | None = None,
    channel: str | None = None,
    analyzed_at: datetime | None = None,
    facts: dict[str, Any] | None = None,
) -> UUID:
    """Bir Review + (verilirse) bire-bir bağlı bir ReviewFact satırı
    yazar, review.id döner. test_analytics.py'nin ``_seed``'iyle AYNI
    ruh — facts alanı burada eklendi."""
    async with admin_session.begin():
        await _bind(admin_session, tenant_id)
        moment = analyzed_at or datetime.now(UTC)
        review = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label=sentiment,
            sentiment_score=score,
            primary_category="kargo",
            primary_confidence=0.8,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            batch_job_id=None,
            analyzed_at=moment,
            review_date=moment,
            overrides_applied=None,
            quality_flag=quality_flag,
            channel=channel,
        )
        admin_session.add(review)
        await admin_session.flush()
        review_id = review.id
        if facts is not None:
            admin_session.add(
                ReviewFact(review_id=review_id, tenant_id=tenant_id, **facts)
            )
            await admin_session.flush()
        admin_session.expunge_all()
    return review_id


async def _attach_viewer(
    admin_session: AsyncSession, *, tenant_id: UUID
) -> tuple[User, str]:
    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"ops-viewer-{tenant_id.hex[:8]}@example.com"
    async with admin_session.begin():
        user = await usvc.create(email=email, password=plain, full_name="Ops Viewer")
        await usvc.attach_to_tenant(
            user_id=user.id, tenant_id=tenant_id, role=UserTenantRole.VIEWER
        )
    return user, plain


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- FactFieldName / FACT_FIELDS consistency --------------------------


def test_fact_field_name_literal_matches_fact_fields() -> None:
    """Pydantic Literal statik olmak zorunda — fact_parsing.FACT_FIELDS
    ile elle senkron tutuluyor; bu test sürüklenmeyi yakalar."""
    assert set(get_args(FactFieldName)) == set(FACT_FIELDS)


# --- GET /tenants/me/operations/summary --------------------------------


@pytest.mark.asyncio
async def test_summary_sla_counts_and_violation_rate(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a",
        facts={"sla_resolution_status": "within"},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b",
        facts={"sla_resolution_status": "violated"},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="c",
        facts={"sla_resolution_status": "violated"},
    )
    await _seed(admin_session, tenant_id=tid, text_value="d")  # facts yok

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/summary", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_reviews"] == 4
    assert body["facts_coverage"]["sla_resolution"] == 3
    assert body["sla"]["resolution"] == {
        "within": 1,
        "violated": 2,
        "violation_rate_pct": pytest.approx(66.67, abs=0.01),
    }


@pytest.mark.asyncio
async def test_summary_avg_and_median_resolution_minutes(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    for minutes in (10, 20, 30):
        await _seed(
            admin_session, tenant_id=tid, text_value=f"row-{minutes}",
            facts={
                "sla_resolution_status": "within",
                "resolution_time_minutes": minutes,
            },
        )
    # Statü dolu ama süre NULL — avg/median bu satırı görmezden gelmeli
    # (percentile_cont/avg NULL'ları elemesine dayanan tasarım varsayımını
    # burada sabitliyoruz; satır olmasa da test yine aynı sonucu verirdi).
    await _seed(
        admin_session, tenant_id=tid, text_value="row-null-duration",
        facts={"sla_resolution_status": "within", "resolution_time_minutes": None},
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/summary", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    sla = r.json()["sla"]
    assert sla["avg_resolution_minutes"] == pytest.approx(20.0)
    assert sla["median_resolution_minutes"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_summary_csat_distribution_and_avg(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    for score in (1, 2, 3, 4, 5):
        await _seed(
            admin_session, tenant_id=tid, text_value=f"csat-{score}",
            facts={"csat_score": score, "csat_raw": str(score)},
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/summary", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    csat = r.json()["csat"]
    assert csat["count"] == 5
    assert csat["avg_score"] == pytest.approx(3.0)
    assert csat["distribution"] == {
        "1": 1, "2": 1, "3": 1, "4": 1, "5": 1,
    }


@pytest.mark.asyncio
async def test_summary_compensation_delivery_and_cost_sums(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a",
        facts={
            "compensation_status": "Onaylandı",
            "delivery_status": "Teslim Edildi",
            "freight_cost": Decimal("100.50"),
            "goods_cost": Decimal("200.25"),
        },
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b",
        facts={
            "compensation_status": "Reddedildi",
            "delivery_status": "Teslim Edildi",
            "freight_cost": Decimal("50.00"),
        },
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/summary", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compensation"]["statuses"] == {
        "Onaylandı": 1, "Reddedildi": 1,
    }
    assert body["compensation"]["freight_cost_sum"] == pytest.approx(150.50)
    assert body["compensation"]["goods_cost_sum"] == pytest.approx(200.25)
    assert body["delivery"]["statuses"] == {"Teslim Edildi": 2}


@pytest.mark.asyncio
async def test_summary_include_flagged_toggle(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="clean",
        facts={"sla_resolution_status": "within"},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="flagged",
        quality_flag="duplicate",
        facts={"sla_resolution_status": "violated"},
    )

    token = login_token(batch_client, user.email, pw, tid)
    default = batch_client.get(
        "/tenants/me/operations/summary", headers=_auth(token)
    )
    assert default.status_code == 200, default.text
    assert default.json()["total_reviews"] == 1

    included = batch_client.get(
        "/tenants/me/operations/summary?include_flagged=true",
        headers=_auth(token),
    )
    assert included.status_code == 200, included.text
    assert included.json()["total_reviews"] == 2


@pytest.mark.asyncio
async def test_summary_date_window_filters_by_review_date(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="inside",
        analyzed_at=datetime(2026, 8, 3, 12, tzinfo=UTC),
        facts={"sla_resolution_status": "within"},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="outside",
        analyzed_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
        facts={"sla_resolution_status": "violated"},
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/summary"
        "?date_from=2026-08-01&date_to=2026-08-05",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total_reviews"] == 1


@pytest.mark.asyncio
async def test_summary_cross_tenant_isolation(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    manual_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _user_a, tid_a, _pw_a = semi_auto_tenant
    user_b, tid_b, pw_b = manual_tenant
    await _seed(
        admin_session, tenant_id=tid_a, text_value="tenant-a-only",
        facts={"sla_resolution_status": "violated"},
    )

    token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
    r = batch_client.get(
        "/tenants/me/operations/summary", headers=_auth(token_b)
    )
    assert r.status_code == 200, r.text
    assert r.json()["total_reviews"] == 0


# --- GET /tenants/me/operations/breakdown ------------------------------


@pytest.mark.asyncio
async def test_breakdown_violation_rate_uses_metric_value_key(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a", channel="FEDEX",
        facts={"sla_resolution_status": "within"},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b", channel="FEDEX",
        facts={"sla_resolution_status": "violated"},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="c", channel="FEDEX",
        facts={"sla_resolution_status": "violated"},
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/breakdown"
        "?dimension=channel&metric_key=violation_rate",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dimension"] == "channel"
    assert body["metric_key"] == "violation_rate"
    assert len(body["buckets"]) == 1
    bucket = body["buckets"][0]
    assert bucket["value"] == "FEDEX"
    assert bucket["count"] == 3
    assert "metric_value" in bucket
    assert "score" not in bucket
    assert bucket["metric_value"] == pytest.approx(66.67, abs=0.01)
    assert body["total_count"] == 3
    assert body["coverage_count"] == 3


@pytest.mark.asyncio
async def test_breakdown_csat_avg_by_dimension(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a", channel="web",
        facts={"csat_score": 2},
    )
    await _seed(
        admin_session, tenant_id=tid, text_value="b", channel="web",
        facts={"csat_score": 4},
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/breakdown?dimension=channel&metric_key=csat_avg",
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    bucket = r.json()["buckets"][0]
    assert bucket["metric_value"] == pytest.approx(3.0)
    assert bucket["count"] == 2


@pytest.mark.asyncio
async def test_breakdown_unknown_dimension_rejected(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/breakdown?dimension=zodiac&metric_key=violation_rate",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_breakdown_unknown_metric_key_rejected(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/breakdown?dimension=channel&metric_key=not_a_metric",
        headers=_auth(token),
    )
    assert r.status_code == 400, r.text


# --- GET /tenants/me/operations/sentiment-correlation -------------------


@pytest.mark.asyncio
async def test_sentiment_correlation_notr_key_mapping(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """DB'de 'NÖTR' saklanır; sözleşme ASCII 'NOTR' anahtarı ister."""
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="a", sentiment="NÖTR",
        facts={"sla_resolution_status": "within"},
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/sentiment-correlation", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    within = r.json()["sla"]["within"]
    assert within["NOTR"] == 1
    assert within["NEGATIF"] == 0
    assert within["POZITIF"] == 0
    assert "NÖTR" not in within


@pytest.mark.asyncio
async def test_sentiment_correlation_csat_matrix_and_agreement(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # csat_high (>=4) + model POZITIF -> tam uyum.
    await _seed(
        admin_session, tenant_id=tid, text_value="a", sentiment="POZITIF",
        facts={"csat_score": 5},
    )
    # csat_low (<=2) + model NEGATIF -> tam uyum.
    await _seed(
        admin_session, tenant_id=tid, text_value="b", sentiment="NEGATIF",
        facts={"csat_score": 1},
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/sentiment-correlation", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    matrix_by_score = {row["csat_score"]: row for row in body["csat_matrix"]}
    assert len(body["csat_matrix"]) == 5
    assert matrix_by_score[5]["POZITIF"] == 1
    assert matrix_by_score[1]["NEGATIF"] == 1
    agreement = body["agreement"]
    assert agreement["csat_high_model_positive_pct"] == pytest.approx(100.0)
    assert agreement["csat_low_model_negative_pct"] == pytest.approx(100.0)
    assert agreement["n_csat"] == 2


@pytest.mark.asyncio
async def test_sentiment_correlation_agreement_null_when_no_csat(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(
        admin_session, tenant_id=tid, text_value="no-facts", sentiment="POZITIF",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/operations/sentiment-correlation", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    agreement = r.json()["agreement"]
    assert agreement["csat_high_model_positive_pct"] is None
    assert agreement["csat_low_model_negative_pct"] is None
    assert agreement["n_csat"] == 0


# --- fact-mappings CRUD -------------------------------------------------


@pytest.mark.asyncio
async def test_fact_mappings_empty_list_for_fresh_tenant(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get("/tenants/me/fact-mappings", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_fact_mappings_put_is_full_replace(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    first = batch_client.put(
        "/tenants/me/fact-mappings",
        headers=_auth(token),
        json=[
            {
                "fact_field": "sla_resolution_status",
                "csv_column_mapping": "cozum_durumu",
                "enabled": True,
            },
            {
                "fact_field": "csat",
                "csv_column_mapping": "anket",
                "enabled": True,
            },
        ],
    )
    assert first.status_code == 200, first.text
    assert {row["fact_field"] for row in first.json()} == {
        "sla_resolution_status", "csat",
    }

    second = batch_client.put(
        "/tenants/me/fact-mappings",
        headers=_auth(token),
        json=[
            {
                "fact_field": "csat",
                "csv_column_mapping": "anket_v2",
                "enabled": False,
            },
        ],
    )
    assert second.status_code == 200, second.text
    rows = second.json()
    assert len(rows) == 1
    assert rows[0] == {
        "fact_field": "csat",
        "csv_column_mapping": "anket_v2",
        "enabled": False,
    }

    listed = batch_client.get("/tenants/me/fact-mappings", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    assert listed.json() == rows


@pytest.mark.asyncio
async def test_fact_mappings_put_rejects_unknown_fact_field(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.put(
        "/tenants/me/fact-mappings",
        headers=_auth(token),
        json=[
            {
                "fact_field": "not_a_real_field",
                "csv_column_mapping": "x",
                "enabled": True,
            }
        ],
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_fact_mappings_viewer_can_read_but_not_write(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _user, tid, _pw = semi_auto_tenant
    viewer, viewer_pw = await _attach_viewer(admin_session, tenant_id=tid)
    token = login_token(batch_client, viewer.email, viewer_pw, tid)

    read = batch_client.get("/tenants/me/fact-mappings", headers=_auth(token))
    assert read.status_code == 200, read.text

    write = batch_client.put(
        "/tenants/me/fact-mappings",
        headers=_auth(token),
        json=[
            {
                "fact_field": "csat",
                "csv_column_mapping": "anket",
                "enabled": True,
            }
        ],
    )
    assert write.status_code == 403, write.text


# --- review-detail facts enrichment ------------------------------------


@pytest.mark.asyncio
async def test_review_detail_includes_facts_when_present(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    review_id = await _seed(
        admin_session, tenant_id=tid, text_value="with-facts",
        facts={
            "sla_resolution_status": "within",
            "csat_score": 5,
            "csat_raw": "Çok memnunum",
        },
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        f"/tenants/me/reviews/{review_id}", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    facts = r.json()["facts"]
    assert facts is not None
    assert facts["sla_resolution_status"] == "within"
    assert facts["csat_score"] == 5
    assert facts["csat_raw"] == "Çok memnunum"


@pytest.mark.asyncio
async def test_review_detail_facts_null_when_no_review_facts_row(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    review_id = await _seed(
        admin_session, tenant_id=tid, text_value="without-facts",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        f"/tenants/me/reviews/{review_id}", headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["facts"] is None
