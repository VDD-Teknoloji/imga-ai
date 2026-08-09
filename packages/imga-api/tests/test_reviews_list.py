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
from imga_core import review_text_hash
from imga_db.models import (
    Review,
    ReviewDecision,
    User,
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
            admin_session, tenant_id=tid, text_value="batch satırı",
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
            admin_session, tenant_id=tid, text_value="batch",
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

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Beta Co"
    )
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

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Beta Co"
    )
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
            admin_session, tenant_id=tid, text_value="ileti A",
            overrides_applied=overrides,
        )
        without_overrides = await _insert_review(
            admin_session, tenant_id=tid, text_value="ileti B",
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
