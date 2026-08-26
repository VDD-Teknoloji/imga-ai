"""Coverage for GET /tenants/me/reviews + /{id}.

Filter surface mirrors the ticket list pattern. We seed the table
directly via SQL inserts so we don't have to drive the worker for each
test — the route is a pure projection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_api.services import AuditService, UserService
from imga_core import review_text_hash
from imga_db.models import (
    Review,
    ReviewDecision,
    User,
    UserTenantRole,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)

# --- seeding helpers ------------------------------------------------------


async def _insert_review(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment: str = "NÖTR",
    score: float = 0.0,
    category: str = "diğer",
    confidence: float = 0.5,
    decision: ReviewDecision = ReviewDecision.SKIPPED_THRESHOLD,
    ticket_id: UUID | None = None,
    batch_job_id: UUID | None = None,
    analyzed_at: datetime | None = None,
    overrides_applied: list[dict[str, object]] | None = None,
    # 2026-08-20 — Dalga 3 boyut filtreleri + dimension-values ucu.
    channel: str | None = None,
    business_segment: str | None = None,
    product_line: str | None = None,
    customer_tier: str | None = None,
    entered_by: str | None = None,
    source: str | None = None,
    quality_flag: str | None = None,
    source_url: str | None = None,
) -> Review:
    review = Review(
        tenant_id=tenant_id,
        text=text_value,
        text_hash=review_text_hash(text_value),
        sentiment_label=sentiment,
        sentiment_score=score,
        primary_category=category,
        primary_confidence=confidence,
        automation_mode="semi_auto",
        decision=decision,
        decision_reason=None,
        ticket_id=ticket_id,
        submitted_by_user_id=None,
        batch_job_id=batch_job_id,
        analyzed_at=analyzed_at or datetime.now(UTC),
        # Liste sıralaması/tarih filtresi review_date ekseninde.
        review_date=analyzed_at or datetime.now(UTC),
        overrides_applied=overrides_applied,
        channel=channel,
        business_segment=business_segment,
        product_line=product_line,
        customer_tier=customer_tier,
        entered_by=entered_by,
        source=source,
        quality_flag=quality_flag,
        source_url=source_url,
    )
    session.add(review)
    await session.flush()
    return review


async def _seed_reviews(
    admin_session: AsyncSession, tenant_id: UUID, count: int = 5
) -> list[Review]:
    rows: list[Review] = []
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        for i in range(count):
            r = await _insert_review(
                admin_session,
                tenant_id=tenant_id,
                text_value=f"yorum {i}",
                sentiment="NEGATIF" if i % 2 == 0 else "POZITIF",
                score=-0.5 if i % 2 == 0 else 0.7,
                category="kargo" if i < 3 else "iade",
                analyzed_at=datetime.now(UTC) - timedelta(minutes=i),
            )
            rows.append(r)
            admin_session.expunge(r)
    return rows


# --- happy path filters ---------------------------------------------------


@pytest.mark.asyncio
async def test_list_and_detail_expose_source_url(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Migration 0047 — tweet/kaynak bağlantısı liste ve detayda döner;
    bağlantısız satırda null."""
    user, tid, pw = semi_auto_tenant
    link = "https://x.com/musteri/status/2092540287411159128"
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        linked = await _insert_review(
            admin_session, tenant_id=tid, text_value="tencere yandı", source_url=link
        )
        plain = await _insert_review(admin_session, tenant_id=tid, text_value="kargo geç")
        linked_id, plain_id = linked.id, plain.id

    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    body = batch_client.get("/tenants/me/reviews", headers=headers).json()
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(linked_id)]["source_url"] == link
    assert by_id[str(plain_id)]["source_url"] is None

    detail = batch_client.get(f"/tenants/me/reviews/{linked_id}", headers=headers).json()
    assert detail["source_url"] == link


@pytest.mark.asyncio
async def test_list_returns_all_reviews_when_no_filters(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed_reviews(admin_session, tid, count=5)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5


@pytest.mark.asyncio
async def test_filter_sentiment_labels_csv(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed_reviews(admin_session, tid, count=5)
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.get(
        "/tenants/me/reviews?sentiment_labels=NEGATIF",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["sentiment_label"] == "NEGATIF" for i in items)
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_filter_has_ticket_true_returns_only_linked(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    # Use seed: row[0] has fake ticket_id, others null.
    fake_ticket = uuid4()
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        # Linked review must reference a real ticket; insert one first.
        await admin_session.execute(
            text(
                "INSERT INTO tickets (id, tenant_id, category_id, state, "
                "priority, title, opened_at, last_state_change_at) "
                "SELECT :tid, :tn, c.id, 'open', 'normal', 'test', now(), now() "
                "FROM categories c WHERE c.code = 'kargo' LIMIT 1"
            ),
            {"tid": str(fake_ticket), "tn": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="ticketlı",
            ticket_id=fake_ticket,
        )
        await _insert_review(admin_session, tenant_id=tid, text_value="ticketsız")

    token = login_token(batch_client, user.email, pw, tid)
    linked = batch_client.get(
        "/tenants/me/reviews?has_ticket=true",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert linked["total"] == 1
    assert all(i["ticket_id"] is not None for i in linked["items"])

    unlinked = batch_client.get(
        "/tenants/me/reviews?has_ticket=false",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert unlinked["total"] == 1
    assert all(i["ticket_id"] is None for i in unlinked["items"])


@pytest.mark.asyncio
async def test_filter_batch_job_id_scopes_to_one_upload(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    batch_id = uuid4()
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        # Insert a stub batch job row so the FK on reviews holds.
        await admin_session.execute(
            text(
                "INSERT INTO analyze_batch_jobs "
                "(id, tenant_id, status, file_name, file_size_bytes, "
                "file_path, text_column, total_rows, created_at) "
                "VALUES (:id, :tid, 'completed', 'x.csv', 100, '/tmp/x', "
                "'yorum', 1, now())"
            ),
            {"id": str(batch_id), "tid": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="batch satırı",
            batch_job_id=batch_id,
        )
        await _insert_review(admin_session, tenant_id=tid, text_value="manuel satır")

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        f"/tenants/me/reviews?batch_job_id={batch_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["batch_job_id"] == str(batch_id)
    assert items[0]["source_type"] == "batch"


@pytest.mark.asyncio
async def test_filter_source_types_distinguishes_manual_and_batch(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    batch_id = uuid4()
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await admin_session.execute(
            text(
                "INSERT INTO analyze_batch_jobs "
                "(id, tenant_id, status, file_name, file_size_bytes, "
                "file_path, text_column, total_rows, created_at) "
                "VALUES (:id, :tid, 'completed', 'x.csv', 100, '/tmp/x', "
                "'yorum', 1, now())"
            ),
            {"id": str(batch_id), "tid": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="batch",
            batch_job_id=batch_id,
        )
        await _insert_review(admin_session, tenant_id=tid, text_value="manuel")

    token = login_token(batch_client, user.email, pw, tid)
    only_manual = batch_client.get(
        "/tenants/me/reviews?source_types=manual",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert only_manual["total"] == 1
    assert only_manual["items"][0]["source_type"] == "manual"


@pytest.mark.asyncio
async def test_pagination_limit_offset_total(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed_reviews(admin_session, tid, count=7)

    token = login_token(batch_client, user.email, pw, tid)
    page1 = batch_client.get(
        "/tenants/me/reviews?limit=3&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    page2 = batch_client.get(
        "/tenants/me/reviews?limit=3&offset=3",
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert page1["total"] == 7
    assert page2["total"] == 7
    assert len(page1["items"]) == 3
    assert len(page2["items"]) == 3
    # Pages don't overlap.
    ids1 = {i["id"] for i in page1["items"]}
    ids2 = {i["id"] for i in page2["items"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_order_by_sentiment_score_asc_and_desc(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed_reviews(admin_session, tid, count=5)

    token = login_token(batch_client, user.email, pw, tid)
    asc = batch_client.get(
        "/tenants/me/reviews?order_by=sentiment_score&order=asc",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    desc = batch_client.get(
        "/tenants/me/reviews?order_by=sentiment_score&order=desc",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    asc_scores = [i["sentiment_score"] for i in asc["items"]]
    desc_scores = [i["sentiment_score"] for i in desc["items"]]
    assert asc_scores == sorted(asc_scores)
    assert desc_scores == sorted(desc_scores, reverse=True)


@pytest.mark.asyncio
async def test_search_filter_matches_text_substring(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await _insert_review(admin_session, tenant_id=tid, text_value="kargom çok geç geldi")
        await _insert_review(admin_session, tenant_id=tid, text_value="iade işlemi sorunsuz")

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews?search=kargo",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert "kargo" in items[0]["text"].lower()


@pytest.mark.asyncio
async def test_rls_isolates_reviews_across_tenants(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _user_a, tid_a, _pw_a = semi_auto_tenant
    await _seed_reviews(admin_session, tid_a, count=2)

    user_b, tid_b, pw_b = await seed_tenant_with_admin(admin_session, name_prefix="Beta Co")
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            "/tenants/me/reviews",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0, "tenant B must not see tenant A's reviews"
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)


@pytest.mark.asyncio
async def test_detail_returns_404_for_other_tenants_review(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _user_a, tid_a, _pw_a = semi_auto_tenant
    seeded = await _seed_reviews(admin_session, tid_a, count=1)
    target_id = seeded[0].id

    user_b, tid_b, pw_b = await seed_tenant_with_admin(admin_session, name_prefix="Beta Co")
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            f"/tenants/me/reviews/{target_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)


@pytest.mark.asyncio
async def test_list_exposes_override_count_and_detail_returns_full_trace(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 8.3.4 — list response includes a per-row override_count
    chip; detail response returns the full JSONB trace verbatim."""
    user, tid, pw = semi_auto_tenant
    overrides = [
        {"layer": "critical", "matched_keywords": ["kötü"], "score": -0.5, "detail": None},
        {"layer": "sla", "matched_keywords": ["3 gün"], "score": -0.3, "detail": "ihlal"},
    ]
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        with_overrides = await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="ileti A",
            overrides_applied=overrides,
        )
        without_overrides = await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="ileti B",
        )
        admin_session.expunge(with_overrides)
        admin_session.expunge(without_overrides)

    token = login_token(batch_client, user.email, pw, tid)
    list_r = batch_client.get(
        "/tenants/me/reviews",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_r.status_code == 200, list_r.text
    by_id = {item["id"]: item for item in list_r.json()["items"]}
    assert by_id[str(with_overrides.id)]["override_count"] == 2
    assert by_id[str(without_overrides.id)]["override_count"] == 0

    detail_r = batch_client.get(
        f"/tenants/me/reviews/{with_overrides.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail_r.status_code == 200
    body = detail_r.json()
    assert len(body["overrides_applied"]) == 2
    assert body["overrides_applied"][0]["layer"] == "critical"
    assert body["overrides_applied"][1]["detail"] == "ihlal"

    # Row predating migration 0014 (overrides_applied IS NULL) returns []
    # so the frontend has a stable list to map over.
    detail_r2 = batch_client.get(
        f"/tenants/me/reviews/{without_overrides.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail_r2.status_code == 200
    assert detail_r2.json()["overrides_applied"] == []


@pytest.mark.asyncio
async def test_reanalysis_marker_excluded_from_count_kept_in_detail(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Yeniden analiz izi (score/matched_keywords alanları YOK) kural
    sayacına girmez ama detay izinde aynen döner — 2026-08-14 detay
    sayfası çökmesinin regresyon testi."""
    user, tid, pw = semi_auto_tenant
    overrides = [
        {"layer": "critical", "matched_keywords": ["kötü"], "score": -0.5, "detail": None},
        {"layer": "reanalysis", "detail": "z-ai/glm-5.2"},
    ]
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        review = await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="yeniden analizli",
            overrides_applied=overrides,
        )
        admin_session.expunge(review)

    token = login_token(batch_client, user.email, pw, tid)
    list_r = batch_client.get(
        "/tenants/me/reviews",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_r.status_code == 200, list_r.text
    by_id = {item["id"]: item for item in list_r.json()["items"]}
    assert by_id[str(review.id)]["override_count"] == 1

    detail_r = batch_client.get(
        f"/tenants/me/reviews/{review.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail_r.status_code == 200
    trace = detail_r.json()["overrides_applied"]
    assert len(trace) == 2
    assert trace[1] == {"layer": "reanalysis", "detail": "z-ai/glm-5.2"}


# ---- 2026-08-20 (Dalga 3) — business-dimension list filters ----------


@pytest.mark.asyncio
async def test_filter_channels_csv_is_case_and_whitespace_insensitive(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """channels= filtresi lower(trim(...)) katlamalı eşleşir — filtre
    chip'i 'fedex' gönderse de DB'deki 'FEDEX' satırını bulur."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="fedex satırı",
            channel="FEDEX",
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="ups satırı",
            channel="UPS",
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews",
        params={"channels": "fedex"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["text"] == "fedex satırı"


@pytest.mark.asyncio
async def test_filter_remaining_business_dimensions_case_insensitive(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """business_segments / product_lines / customer_tiers /
    entered_bys / sources — beşi de channels ile aynı lower(trim)
    katlama kuralını izler."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="hedef satır",
            business_segment="Satış",
            product_line="Kargo",
            customer_tier="Kurumsal",
            entered_by="Mehmet Demir",
            source="Portal",
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="alakasız satır",
            business_segment="Pazarlama",
            product_line="Değişim",
            customer_tier="Bireysel",
            entered_by="Ali Kaya",
            source="Phone",
        )

    token = login_token(batch_client, user.email, pw, tid)
    checks = [
        ("business_segments", "satış"),
        ("product_lines", "kargo"),
        ("customer_tiers", "kurumsal"),
        ("entered_bys", "mehmet demir"),
        ("sources", "portal"),
    ]
    for param, value in checks:
        r = batch_client.get(
            "/tenants/me/reviews",
            params={param: value},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1, f"{param}={value} beklenmedik sonuç: {items}"
        assert items[0]["text"] == "hedef satır"


# ---- 2026-08-20 (Dalga 3) — GET /tenants/me/reviews/dimension-values -


@pytest.mark.asyncio
async def test_dimension_values_folds_and_labels_most_frequent_spelling(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """'FEDEX' (x4) + 'fedex' (x1) tek girdiye katlanır, etiket en sık
    ham varyantı (FEDEX); count desc sıralı döner."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        for i in range(4):
            await _insert_review(
                admin_session,
                tenant_id=tid,
                text_value=f"fedex-{i}",
                channel="FEDEX",
            )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="fedex-minor",
            channel="fedex",
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="ups-1",
            channel="UPS",
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews/dimension-values",
        params={"field": "channel"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    values = r.json()["values"]
    assert {v["value"]: v["count"] for v in values} == {"FEDEX": 5, "UPS": 1}
    assert values[0]["value"] == "FEDEX"  # count desc


@pytest.mark.asyncio
async def test_dimension_values_rejects_unknown_field(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews/dimension-values",
        params={"field": "zodiac_sign"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_dimension_values_include_flagged_defaults_to_true(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Bu uç bir filtre-chip kaynağıdır (liste gibi arşive bakar):
    include_flagged varsayılanı True — analitiğin False
    varsayılanından bilinçli olarak farklı."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="flagged",
            channel="DHL",
            quality_flag="duplicate",
        )

    token = login_token(batch_client, user.email, pw, tid)
    default = batch_client.get(
        "/tenants/me/reviews/dimension-values",
        params={"field": "channel"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert default.status_code == 200, default.text
    assert default.json()["values"] == [{"value": "DHL", "count": 1}]

    excluded = batch_client.get(
        "/tenants/me/reviews/dimension-values",
        params={"field": "channel", "include_flagged": "false"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["values"] == []


@pytest.mark.asyncio
async def test_dimension_values_caps_at_100_and_orders_by_count_desc(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """LIMIT 100 + count desc: 105 farklı ham değerden en çok görülen
    (x2) ilk sırada; yanıt 100 satırla kesilir."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        for i in range(105):
            await _insert_review(
                admin_session,
                tenant_id=tid,
                text_value=f"kanal metni {i}",
                channel=f"kanal-{i}",
            )
        # Bir değeri ikinci kez ekleyip en yüksek sayaca taşı — count
        # desc sıralamasının gerçekten çalıştığını doğrular.
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="kanal-0 tekrar",
            channel="kanal-0",
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews/dimension-values",
        params={"field": "channel"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    values = r.json()["values"]
    assert len(values) == 100
    assert values[0] == {"value": "kanal-0", "count": 2}


@pytest.mark.asyncio
async def test_dimension_values_route_is_not_shadowed_by_review_id_path(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Starlette rota sırası regresyon koruması: GET /dimension-values
    'review_id: UUID' path parametresine düşüp 422 dönmemeli — bu uç
    list_reviews'dan hemen sonra, get_review'dan ÖNCE kayıtlı olmalı."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews/dimension-values",
        params={"field": "channel"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"values": []}


@pytest.mark.asyncio
async def test_dimension_values_viewer_role_can_access(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Uç _AnyMember ile korunuyor (TENANT_ADMIN/ANALYST/VIEWER hepsi
    okuyabilir) — yanlışlıkla _WriteMember'a düşürülmesine karşı
    regresyon koruması."""
    _admin, tid, _pw = semi_auto_tenant

    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    viewer_pw = "Viewer-Pass-123!"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=f"viewer-{uuid4().hex[:6]}@example.com",
            password=viewer_pw,
            full_name="Viewer User",
        )
        await usvc.attach_to_tenant(user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER)
        viewer_id = viewer.id
        viewer_email = viewer.email

    try:
        token = login_token(batch_client, viewer_email, viewer_pw, tid)
        r = batch_client.get(
            "/tenants/me/reviews/dimension-values",
            params={"field": "channel"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": str(viewer_id)}
            )
