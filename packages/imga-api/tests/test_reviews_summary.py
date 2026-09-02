"""Coverage for GET /tenants/me/reviews/summary (W2-A).

Mirrors test_reviews_list.py's seeding style (direct SQL/ORM inserts
under an RLS-bound ``set_config`` block) but keeps its own local
``_insert_review`` — extended with ``content_type``/``nps_score`` —
rather than importing the list suite's helper, per the file-ownership
split for this task.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token

# --- seeding helpers -------------------------------------------------


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
    source: str | None = None,
    entered_by: str | None = None,
    quality_flag: str | None = None,
    content_type: str | None = None,
    nps_score: int | None = None,
    review_date: datetime | None = None,
    source_meta: dict[str, int] | None = None,
) -> Review:
    when = review_date or datetime.now(UTC)
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
        batch_job_id=None,
        analyzed_at=when,
        # Liste/özet sıralaması ve gün bucket'ları review_date ekseninde.
        review_date=when,
        source=source,
        entered_by=entered_by,
        quality_flag=quality_flag,
        content_type=content_type,
        nps_score=nps_score,
        source_meta=source_meta,
    )
    session.add(review)
    await session.flush()
    return review


async def _insert_ticket(session: AsyncSession, *, tenant_id: UUID) -> UUID:
    """A minimal open ticket so a review's ``ticket_id`` FK holds —
    same pattern as test_reviews_list.py's has_ticket test."""
    ticket_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO tickets (id, tenant_id, category_id, state, "
            "priority, title, opened_at, last_state_change_at) "
            "SELECT :tid, :tn, c.id, 'open', 'normal', 'test', now(), now() "
            "FROM categories c WHERE c.code = 'kargo' LIMIT 1"
        ),
        {"tid": str(ticket_id), "tn": str(tenant_id)},
    )
    return ticket_id


async def _seed_summary_reviews(session: AsyncSession, tenant_id: UUID) -> None:
    """10 rows spanning sentiment/source/entered_by/quality_flag/
    content_type('question')/nps_score, across three review_date days
    (D0=today, D1=yesterday, D2=two days ago at a fixed hour, so the
    daily bucketing doesn't straddle a UTC midnight by accident)."""
    base = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    d0, d1, d2 = base, base - timedelta(days=1), base - timedelta(days=2)

    async with session.begin():
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        ticket_id = await _insert_ticket(session, tenant_id=tenant_id)

        # D0 — 5 rows (2 negatif kargo, 2 nötr soru-kargo, 1 pozitif nps)
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="kargo geç geldi 1",
            sentiment="NEGATIF",
            score=-0.6,
            category="kargo",
            source="Email",
            entered_by="Ayşe Yılmaz",
            review_date=d0,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="kargo geç geldi 2",
            sentiment="NEGATIF",
            score=-0.4,
            category="kargo",
            source="Email",
            entered_by="Ayşe Yılmaz",
            quality_flag="duplicate",
            review_date=d0,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="Kargo ne zaman gelir?",
            sentiment="NÖTR",
            score=0.0,
            category="kargo",
            source="Email",
            entered_by="Mehmet Demir",
            content_type="question",
            review_date=d0,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="Kargo ne zaman gelir?",
            sentiment="NÖTR",
            score=0.0,
            category="kargo",
            source="Email",
            entered_by="Mehmet Demir",
            content_type="question",
            review_date=d0,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="hızlı teslimat, teşekkürler",
            sentiment="POZITIF",
            score=0.8,
            category="kargo",
            source="Email",
            entered_by="Ayşe Yılmaz",
            nps_score=9,
            review_date=d0,
        )

        # D1 — 2 rows (1 pozitif iade, 1 nötr iade+ticket)
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="iade sorunsuz tamamlandı",
            sentiment="POZITIF",
            score=0.5,
            category="iade",
            source="Portal",
            entered_by="Mehmet Demir",
            review_date=d1,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="iade süreci beklemede",
            sentiment="NÖTR",
            score=0.0,
            category="iade",
            source="Portal",
            entered_by="Mehmet Demir",
            quality_flag="empty",
            ticket_id=ticket_id,
            review_date=d1,
        )

        # D2 — 3 rows (1 negatif diğer/informational, 1 pozitif diğer/
        # meaningless/entered_by NULL, 1 negatif iade/question)
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="bilgi amaçlı yorum",
            sentiment="NEGATIF",
            score=-0.7,
            category="diğer",
            source="Phone",
            entered_by="Ayşe Yılmaz",
            quality_flag="informational",
            review_date=d2,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="asdkjf qwer",
            sentiment="POZITIF",
            score=0.6,
            category="diğer",
            source="Phone",
            entered_by=None,
            quality_flag="meaningless",
            review_date=d2,
        )
        await _insert_review(
            session,
            tenant_id=tenant_id,
            text_value="İade ücretsiz mi?",
            sentiment="NEGATIF",
            score=-0.5,
            category="iade",
            source="Portal",
            entered_by="Ayşe Yılmaz",
            content_type="question",
            review_date=d2,
        )


# --- tests -------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_full_shape(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Seeds the 10-row fixture and checks every bucket of the summary
    shape in one pass — totals, sentiment, quality (incl. clean),
    entered_by matrix, categories, sources, NPS, ticket_linked, avg
    score, daily buckets and top_questions grouping."""
    user, tid, pw = semi_auto_tenant
    await _seed_summary_reviews(admin_session, tid)
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.get(
        "/tenants/me/reviews/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] == 10
    assert body["sentiment"] == {"NEGATIF": 4, "NÖTR": 3, "POZITIF": 3}
    assert body["avg_sentiment_score"] == pytest.approx(-0.03, abs=1e-6)
    assert body["ticket_linked"] == 1
    assert body["question_count"] == 3
    # 2026-09-01 (migration 0050) — content_types carries all five keys;
    # the fixture only seeds 'question' rows, the other four 0-default.
    assert body["content_types"] == {
        "question": 3,
        "suggestion": 0,
        "thanks": 0,
        "request": 0,
        "escalation": 0,
    }

    assert body["quality"] == {
        "clean": 6,
        "duplicate": 1,
        "empty": 1,
        "informational": 1,
        "meaningless": 1,
    }

    nps = body["nps"]
    assert nps == {
        "promoter": 1,
        "passive": 0,
        "detractor": 0,
        "with_nps": 1,
        "score": 100.0,
    }

    sources = {s["value"]: s["count"] for s in body["sources"]}
    assert sources == {"Email": 5, "Portal": 3, "Phone": 2}

    categories = {c["code"]: (c["count"], c["negative_count"]) for c in body["categories"]}
    assert categories == {
        "kargo": (5, 2),
        "iade": (3, 1),
        "diğer": (2, 1),
    }

    entered_by = {e["value"]: e for e in body["entered_by"]}
    # NULL entered_by (row "asdkjf qwer") never surfaces as a bucket —
    # only the two named reps show up.
    assert set(entered_by) == {"Ayşe Yılmaz", "Mehmet Demir"}
    assert entered_by["Ayşe Yılmaz"]["total"] == 5
    assert entered_by["Ayşe Yılmaz"]["flagged"] == 2
    assert entered_by["Ayşe Yılmaz"]["question"] == 1
    assert entered_by["Ayşe Yılmaz"]["negative"] == 4
    assert entered_by["Mehmet Demir"]["total"] == 4
    assert entered_by["Mehmet Demir"]["flagged"] == 1
    assert entered_by["Mehmet Demir"]["question"] == 2
    assert entered_by["Mehmet Demir"]["negative"] == 0

    top_questions = body["top_questions"]
    assert len(top_questions) == 2
    assert top_questions[0] == {"text": "Kargo ne zaman gelir?", "count": 2}
    assert top_questions[1] == {"text": "İade ücretsiz mi?", "count": 1}

    daily = {d["date"]: (d["count"], d["negative"]) for d in body["daily"]}
    assert sum(c for c, _ in daily.values()) == 10
    counts_sorted = sorted(daily.values(), reverse=True)
    assert counts_sorted[0] == (5, 2)  # D0
    assert (2, 0) in daily.values()  # D1
    assert (3, 2) in daily.values()  # D2
    # Ascending by date.
    dates = list(daily.keys())
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_summary_is_filter_reactive(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """sentiment_labels=NEGATIF narrows every bucket, not just the
    top-line total — proof _build_conditions is shared end-to-end."""
    user, tid, pw = semi_auto_tenant
    await _seed_summary_reviews(admin_session, tid)
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.get(
        "/tenants/me/reviews/summary",
        params={"sentiment_labels": "NEGATIF"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] == 4
    assert body["sentiment"] == {"NEGATIF": 4, "NÖTR": 0, "POZITIF": 0}
    assert body["avg_sentiment_score"] == pytest.approx(-0.55, abs=1e-6)
    assert body["ticket_linked"] == 0  # the ticketed row is NÖTR
    assert body["question_count"] == 1
    assert body["nps"]["with_nps"] == 0
    assert body["nps"]["score"] is None

    categories = {c["code"]: c["count"] for c in body["categories"]}
    assert categories == {"kargo": 2, "diğer": 1, "iade": 1}

    entered_by = {e["value"]: e["total"] for e in body["entered_by"]}
    # Mehmet Demir has no NEGATIF rows in the fixture — drops out entirely.
    assert "Mehmet Demir" not in entered_by
    assert entered_by["Ayşe Yılmaz"] == 4

    assert len(body["top_questions"]) == 1
    assert body["top_questions"][0] == {"text": "İade ücretsiz mi?", "count": 1}


@pytest.mark.asyncio
async def test_list_content_types_filter_narrows_to_questions(
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
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="Kargom ne zaman gelir?",
            content_type="question",
        )
        await _insert_review(admin_session, tenant_id=tid, text_value="normal yorum")

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews",
        params={"content_types": "question"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["content_type"] == "question"
    assert items[0]["text"] == "Kargom ne zaman gelir?"


@pytest.mark.asyncio
async def test_summary_content_types_and_escalation_filter(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """2026-09-01 (migration 0050) — one row per content_type value plus
    one plain row: /summary's content_types dict counts each bucket
    (question_count stays in sync as the 'question' alias), and the
    list's content_types=escalation filter narrows to just that row."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        for ctype, text_value in (
            ("question", "Kargom ne zaman gelir?"),
            ("suggestion", "Keşke daha hızlı kargo olsa."),
            ("thanks", "Teşekkürler, çok memnun kaldım."),
            ("request", "İade istiyorum."),
            ("escalation", "Tüketici hakem heyetine başvuracağım."),
        ):
            await _insert_review(
                admin_session, tenant_id=tid, text_value=text_value, content_type=ctype
            )
        await _insert_review(admin_session, tenant_id=tid, text_value="normal yorum")

    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    summary = batch_client.get("/tenants/me/reviews/summary", headers=headers).json()
    assert summary["content_types"] == {
        "question": 1,
        "suggestion": 1,
        "thanks": 1,
        "request": 1,
        "escalation": 1,
    }
    assert summary["question_count"] == summary["content_types"]["question"]

    r = batch_client.get(
        "/tenants/me/reviews",
        params={"content_types": "escalation"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["content_type"] == "escalation"
    assert items[0]["text"] == "Tüketici hakem heyetine başvuracağım."


@pytest.mark.asyncio
async def test_list_and_detail_expose_content_type(
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
        question = await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="Ürün ne zaman stoğa girer?",
            content_type="question",
        )
        plain = await _insert_review(admin_session, tenant_id=tid, text_value="normal yorum")
        question_id, plain_id = question.id, plain.id

    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    body = batch_client.get("/tenants/me/reviews", headers=headers).json()
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(question_id)]["content_type"] == "question"
    assert by_id[str(plain_id)]["content_type"] is None

    detail = batch_client.get(f"/tenants/me/reviews/{question_id}", headers=headers).json()
    assert detail["content_type"] == "question"

    detail_plain = batch_client.get(f"/tenants/me/reviews/{plain_id}", headers=headers).json()
    assert detail_plain["content_type"] is None


@pytest.mark.asyncio
async def test_detail_exposes_source_meta(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Migration 0049 — tweet import gibi kaynaklardan gelen sayaçlar
    (like_count vb.) detail'de görünmeli."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        review = await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="Bu ürünü çok beğendim",
            source_meta={"like_count": 5},
        )
        review_id = review.id

    token = login_token(batch_client, user.email, pw, tid)
    detail = batch_client.get(
        f"/tenants/me/reviews/{review_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert detail["source_meta"] == {"like_count": 5}


# --- B3 — engagement sort + viral_negative_count ----------------------


@pytest.mark.asyncio
async def test_summary_viral_negative_count(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """viral_negative_count counts NEGATIF rows whose Twitter engagement
    (like+retweet+reply from source_meta) meets VIRAL_ENGAGEMENT_
    THRESHOLD (100). The second row's engagement (10) proves the
    threshold actually excludes sub-threshold complaints rather than
    counting every NEGATIF row with any source_meta at all; its huge
    view_count proves view_count doesn't leak into the engagement sum."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="Bu kargo firmasi rezalet, herkes duysun!",
            sentiment="NEGATIF",
            score=-0.8,
            source="Twitter",
            source_meta={
                "like_count": 100,
                "retweet_count": 30,
                "reply_count": 20,
                "view_count": 50_000,
            },
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="kargo biraz gec geldi",
            sentiment="NEGATIF",
            score=-0.3,
            source="Twitter",
            source_meta={
                "like_count": 5,
                "retweet_count": 3,
                "reply_count": 2,
                "view_count": 500_000,
            },
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["viral_negative_count"] == 1


@pytest.mark.asyncio
async def test_list_order_by_engagement_desc(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """order_by=engagement sorts the most-engaged Twitter row first; a
    row with no source_meta at all (engagement 0, no tie with anything
    else here) sorts last."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="viral sikayet",
            sentiment="NEGATIF",
            source="Twitter",
            source_meta={"like_count": 100, "retweet_count": 30, "reply_count": 20},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="az etkilesimli sikayet",
            sentiment="NEGATIF",
            source="Twitter",
            source_meta={"like_count": 5, "retweet_count": 3, "reply_count": 2},
        )
        await _insert_review(
            admin_session,
            tenant_id=tid,
            text_value="kaynak metasi olmayan yorum",
            sentiment="NÖTR",
            source="Email",
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/reviews",
        params={"order_by": "engagement", "order": "desc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 3
    assert items[0]["text"] == "viral sikayet"
    assert items[-1]["text"] == "kaynak metasi olmayan yorum"
