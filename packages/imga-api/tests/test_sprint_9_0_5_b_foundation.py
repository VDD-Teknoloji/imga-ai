"""Sprint 9.0.5-B foundation regression coverage.

Backend slice of the sprint:
  * E — executive_briefing + trend_alert services use canonical NPS
        from AnalyticsService.compute_nps_summary instead of the raw
        0-10 ``func.avg(nps_score)``.
  * I — trend_alert evaluate filters out fingerprints already
        emitted today; the per-day UNIQUE INDEX from migration 0024
        is the race-safe backstop.
  * H — compute_headline_metrics accepts a ``batch_id`` kwarg that
        scopes review-side metrics to a single batch job; ticket-
        side metrics stay tenant-wide.
  * G — ActionExtractionService is idempotent on (tenant, source,
        fingerprint); a second call with identical content returns
        the existing action_item_ids without minting duplicates.

Frontend slices (A SSE, B /pending-webhooks page, C dispatch
toggle, D mobile sweep) defer to Sprint 9.0.5-C.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from imga_core import review_text_hash
from imga_db.models import (
    ActionItemExtractionLog,
    AnalyzeBatchJob,
    BatchJobStatus,
    ExecutiveBriefing,
    Review,
    ReviewDecision,
    TrendAlert,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.action_extraction_service import (
    EXTRACTION_VERSION,
    ActionExtractionService,
)
from imga_api.services.analytics_service import AnalyticsService
from imga_api.services.executive_briefing_service import (
    ExecutiveBriefingService,
)
from imga_api.services.trend_alert_service import TrendAlertService


# --- helpers ----------------------------------------------------------


async def _seed_review_with_nps(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    nps_score: int | None,
    sentiment_label: str = "NÖTR",
    sentiment_score: float = 0.0,
    created_at: datetime | None = None,
    batch_job_id: UUID | None = None,
) -> Review:
    """Insert a Review with the given NPS + optional explicit
    timestamps. Mirrors test_analytics_nps._seed_nps_review."""
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
            "primary_category": "kargo",
            "primary_confidence": 0.5,
            "automation_mode": "semi_auto",
            "decision": ReviewDecision.SKIPPED_THRESHOLD,
            "decision_reason": None,
            "ticket_id": None,
            "submitted_by_user_id": None,
            "batch_job_id": batch_job_id,
            "analyzed_at": datetime.now(UTC),
            "nps_score": nps_score,
        }
        if created_at is not None:
            kwargs["created_at"] = created_at
            kwargs["review_date"] = created_at
        review = Review(**kwargs)
        admin_session.add(review)
        await admin_session.flush()
        admin_session.expunge(review)
    return review


async def _seed_executive_briefing(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
) -> ExecutiveBriefing:
    """Minimum executive_briefings row so FK targets exist when the
    action-extraction tests use ``source_type='executive_briefing'``."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        today = datetime.now(UTC).date()
        briefing = ExecutiveBriefing(
            tenant_id=tenant_id,
            period="month",
            date_from=today - timedelta(days=30),
            date_to=today,
            headline="seed briefing",
            kpi_changes=[],
            critical_insights=[],
            top_actions=[],
            input_stats={},
            model_name="stub",
            created_at=datetime.now(UTC),
        )
        admin_session.add(briefing)
        await admin_session.flush()
        admin_session.expunge(briefing)
    return briefing


async def _seed_batch_job(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> AnalyzeBatchJob:
    """Minimum AnalyzeBatchJob row so a batch_id-scoped query has
    a real FK target. Status=COMPLETED so it looks done."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        job = AnalyzeBatchJob(
            tenant_id=tenant_id,
            triggered_by_user_id=user_id,
            status=BatchJobStatus.COMPLETED,
            file_name="seed.csv",
            file_size_bytes=42,
            file_path="/tmp/seed.csv",
            text_column="yorum",
            source_column=None,
            auto_create_tickets=False,
            total_rows=10,
            processed_rows=10,
            succeeded_rows=10,
            failed_rows=0,
            tickets_created=0,
            duplicates_skipped=0,
            error_summary=[],
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC) - timedelta(seconds=5),
            completed_at=datetime.now(UTC),
        )
        admin_session.add(job)
        await admin_session.flush()
        admin_session.expunge(job)
    return job


# --- E. NPS canonical -------------------------------------------------


@pytest.mark.asyncio
async def test_executive_briefing_nps_uses_canonical_score(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.0.5-B E — _compute_stats now returns the canonical
    -100..100 NPS via compute_nps_summary instead of the raw 0-10
    average. Seed 50 promoters + 50 detractors → score 0
    ((50-50)/100*100 = 0). The pre-fix code would return ~5.0
    (avg(0+10)/2 = 5)."""
    _user, tid, _pw = semi_auto_tenant

    today = datetime.now(UTC)
    for i in range(50):
        await _seed_review_with_nps(
            admin_session, tenant_id=tid, text_value=f"p-{i}",
            nps_score=10, created_at=today,
        )
    for i in range(50):
        await _seed_review_with_nps(
            admin_session, tenant_id=tid, text_value=f"d-{i}",
            nps_score=0, created_at=today,
        )

    service = ExecutiveBriefingService(
        admin_session, tenant_id=tid, user_id=None,
    )
    # Wrap the service call in an explicit transaction + RLS bind so
    # SQLAlchemy doesn't leave an implicit transaction open after
    # the SELECT (which trips the cleanup_tenant fixture's
    # ``async with begin()`` on teardown).
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        stats = await service._compute_stats(  # noqa: SLF001
            date_from=today.date() - timedelta(days=1),
            date_to=today.date() + timedelta(days=1),
            batch_id=None,
        )
    # Canonical: (50 promoter - 50 detractor) / 100 * 100 = 0.0.
    # Pre-9.0.5-B raw avg would be (50*10 + 50*0)/100 = 5.0.
    assert stats.nps_score == 0.0, (
        f"NPS still on the raw 0-10 scale: got {stats.nps_score}; "
        "expected canonical 0 for a 50/50 split"
    )
    assert stats.nps_bearing_count == 100
    # Coverage: 100 NPS rows / 100 total = 100%.
    assert stats.nps_coverage_percent == 100.0


@pytest.mark.asyncio
async def test_trend_alert_stats_use_canonical_nps(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.0.5-B E — TrendAlertService._stats reads the
    canonical NPS too. With 100% promoters, NPS = +100; the old
    raw-avg path would return 10."""
    _user, tid, _pw = semi_auto_tenant
    today = datetime.now(UTC)
    for i in range(20):
        await _seed_review_with_nps(
            admin_session, tenant_id=tid, text_value=f"prom-{i}",
            nps_score=10, created_at=today - timedelta(days=1),
        )
    service = TrendAlertService(admin_session)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        stats = await service._stats(  # noqa: SLF001
            tid,
            today - timedelta(days=7),
            today,
        )
    assert stats.nps_score == 100.0, (
        f"trend NPS still on raw 0-10 scale: got {stats.nps_score}; "
        "expected canonical 100 for all-promoter window"
    )


# --- I. Trend alert dedupe -------------------------------------------


@pytest.mark.asyncio
async def test_trend_alert_dedupe_filters_same_day_fingerprint(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.0.5-B I — re-running evaluate inside the same UTC
    day with the same condition returns 0 alerts because the
    fingerprint already landed earlier."""
    _user, tid, _pw = semi_auto_tenant

    # Seed an existing alert with a known fingerprint stamped today.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        existing = TrendAlert(
            tenant_id=tid,
            alert_type="nps_drop_week",
            severity="warning",
            title="seeded",
            description="seeded for fingerprint dedupe test",
            evidence={},
            fingerprint="dedupe-test-fingerprint",
            evaluated_at=datetime.now(UTC),
        )
        admin_session.add(existing)

    service = TrendAlertService(admin_session)
    candidates = [
        TrendAlert(
            tenant_id=tid,
            alert_type="nps_drop_week",
            severity="warning",
            title="candidate (should be filtered)",
            description="candidate",
            evidence={},
            fingerprint="dedupe-test-fingerprint",
        ),
        TrendAlert(
            tenant_id=tid,
            alert_type="negative_sentiment_jump",
            severity="warning",
            title="candidate (fresh fingerprint)",
            description="candidate",
            evidence={},
            fingerprint="fresh-fingerprint",
        ),
    ]
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        survivors = await service._filter_already_emitted_today(  # noqa: SLF001
            tid, candidates, datetime.now(UTC),
        )
    assert len(survivors) == 1
    assert survivors[0].fingerprint == "fresh-fingerprint"


# --- H. compute_headline_metrics batch_id scoping --------------------


@pytest.mark.asyncio
async def test_headline_metrics_batch_id_scopes_to_batch(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.0.5-B H — review-side metrics scope to the batch
    when ``batch_id`` is set. Seed 5 reviews under batch A and
    3 reviews tenant-wide; batch-scoped query returns 5,
    tenant-wide returns 8."""
    user, tid, _pw = semi_auto_tenant

    job = await _seed_batch_job(admin_session, tenant_id=tid, user_id=user.id)
    today = datetime.now(UTC)
    for i in range(5):
        await _seed_review_with_nps(
            admin_session, tenant_id=tid, text_value=f"batch-{i}",
            nps_score=9, created_at=today, batch_job_id=job.id,
        )
    for i in range(3):
        await _seed_review_with_nps(
            admin_session, tenant_id=tid, text_value=f"adhoc-{i}",
            nps_score=2, created_at=today, batch_job_id=None,
        )

    analytics = AnalyticsService(admin_session)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        scoped = await analytics.compute_headline_metrics(
            tenant_id=tid,
            batch_id=job.id,
        )
        wide = await analytics.compute_headline_metrics(tenant_id=tid)

    assert scoped.total_reviews == 5
    assert wide.total_reviews == 8
    # NPS on the batch is +100 (5 promoters); tenant-wide blends
    # promoters + detractors so the score is lower.
    assert scoped.nps_score == 100.0
    assert wide.nps_score is not None and wide.nps_score < 100.0


@pytest.mark.asyncio
async def test_headline_metrics_no_batch_id_is_tenant_wide(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Backward compat — passing no batch_id behaves identically to
    pre-Sprint-9.0.5-B (default keyword arg path)."""
    _user, tid, _pw = semi_auto_tenant
    today = datetime.now(UTC)
    for i in range(3):
        await _seed_review_with_nps(
            admin_session, tenant_id=tid, text_value=f"row-{i}",
            nps_score=8, created_at=today,
        )

    analytics = AnalyticsService(admin_session)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        result = await analytics.compute_headline_metrics(tenant_id=tid)
    assert result.total_reviews == 3


# --- G. ActionExtractionService idempotency --------------------------


@pytest.mark.asyncio
async def test_action_extraction_idempotent_on_repeat(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.0.5-B G — calling extract twice with identical
    content returns the same action_item_ids without minting
    duplicates. The second call is a SELECT against the UNIQUE
    constraint, no INSERT into action_items."""
    _user, tid, _pw = semi_auto_tenant

    # FK target — action_items.source_briefing_id references
    # executive_briefings.id; seed a real row so the foreign-key
    # constraint is satisfied.
    briefing = await _seed_executive_briefing(admin_session, tenant_id=tid)
    source_id = briefing.id
    payloads = [
        {
            "title": "Follow up with delivery team",
            "description": "Urgent delivery delays — investigate",
            "priority": "high",
        },
        {
            "title": "Customer service training",
            "description": "Improve response empathy",
            "priority": "medium",
        },
    ]
    content = "Top actions: deliver fast, train CS"

    service = ActionExtractionService(admin_session)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        first_ids = await service.extract(
            tenant_id=tid,
            source_type="executive_briefing",
            source_id=source_id,
            content_text=content,
            action_payloads=payloads,
        )

    assert len(first_ids) == 2

    # Second call: same content, same source_id → no new rows.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        second_ids = await service.extract(
            tenant_id=tid,
            source_type="executive_briefing",
            source_id=source_id,
            content_text=content,
            action_payloads=payloads,
        )

    assert second_ids == first_ids


@pytest.mark.asyncio
async def test_action_extraction_content_change_re_extracts(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A content edit yields a different fingerprint, so a fresh
    set of ActionItem rows is minted (the operator regenerated the
    SWOT, prose changed, follow-up tasks should reflect the new
    content)."""
    _user, tid, _pw = semi_auto_tenant
    # Use executive_briefing as the source so we can reuse the
    # _seed_executive_briefing helper (the parallel
    # _seed_strategic_report would add cruft for no test value —
    # the property under test is fingerprint-based re-extraction,
    # which is source-type-agnostic).
    briefing = await _seed_executive_briefing(admin_session, tenant_id=tid)
    source_id = briefing.id
    payloads = [
        {
            "title": "First version action",
            "description": "Initial extraction",
            "priority": "low",
        }
    ]

    service = ActionExtractionService(admin_session)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        first_ids = await service.extract(
            tenant_id=tid,
            source_type="executive_briefing",
            source_id=source_id,
            content_text="Original briefing content",
            action_payloads=payloads,
        )

    new_payloads = [
        {
            "title": "Second version action",
            "description": "Revised extraction",
            "priority": "high",
        }
    ]
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        second_ids = await service.extract(
            tenant_id=tid,
            source_type="executive_briefing",
            source_id=source_id,
            content_text="Revised briefing content",  # different content
            action_payloads=new_payloads,
        )

    # Different fingerprint → different ids minted.
    assert set(first_ids).isdisjoint(set(second_ids))
    assert len(second_ids) == 1


def test_action_extraction_version_constant_is_v1() -> None:
    """Pin the extraction-version constant. Bumping it invalidates
    every existing log row's fingerprint and forces re-extraction —
    a deliberate operator action, not something a refactor should
    change accidentally."""
    assert EXTRACTION_VERSION == "v1"


# --- Migration 0024 schema smoke -------------------------------------


@pytest.mark.asyncio
async def test_migration_0024_schema_in_place(
    admin_session: AsyncSession,
) -> None:
    """Sprint 9.0.5-B Migration 0024 creates two table additions +
    one new table. Smoke-test by querying the catalog directly so
    a future revert doesn't silently lose the columns."""
    cols_briefings = await admin_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='executive_briefings' "
            "AND column_name='top_action_item_ids'"
        )
    )
    assert cols_briefings.scalar_one_or_none() == "top_action_item_ids"

    cols_alerts = await admin_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='trend_alerts' "
            "AND column_name IN ('fingerprint', 'evaluated_at') "
            "ORDER BY column_name"
        )
    )
    rows = [r[0] for r in cols_alerts.all()]
    assert rows == ["evaluated_at", "fingerprint"]

    log_table = await admin_session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name='action_items_extraction_log'"
        )
    )
    assert log_table.scalar_one_or_none() == "action_items_extraction_log"

    # Sanity — the unique constraint exists and the partial index too.
    uq = await admin_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename='trend_alerts' "
            "AND indexname='uq_trend_alerts_fingerprint_per_day'"
        )
    )
    assert uq.scalar_one_or_none() == "uq_trend_alerts_fingerprint_per_day"

    extraction_uq = await admin_session.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conname='uq_action_extraction_log_fingerprint'"
        )
    )
    assert extraction_uq.scalar_one_or_none() == (
        "uq_action_extraction_log_fingerprint"
    )

    _ = ActionItemExtractionLog  # Surface the import so flake8 / mypy
    # see it; the test reads schema metadata, not ORM rows.


@pytest.mark.asyncio
async def test_select_extraction_log_via_orm(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """ORM mapper smoke for ActionItemExtractionLog — a fresh
    tenant has zero rows, the model loads without erroring on
    unknown columns. Pins that the model + table stay in sync."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(ActionItemExtractionLog).where(
                    ActionItemExtractionLog.tenant_id == tid
                )
            )
        ).scalars().all()
    assert rows == []
