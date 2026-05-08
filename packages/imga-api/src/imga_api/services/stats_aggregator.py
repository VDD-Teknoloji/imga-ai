"""Stats snapshot for SWOT/OKR generation.

Sprint 8.3.6 / Alt-Faz 8.3.6.3.A. The SWOT generator (and Sprint
8.3.6.4 OKR generator) need a single, internally-consistent picture
of a tenant's review-side data. Building that picture from per-
endpoint analytics queries via HTTP would re-authenticate, re-bind
RLS, and round-trip the network six times; running them through
``AnalyticsService`` directly stays inside one bound session.

``StrategicStatsSnapshot`` is the wire shape. ``stats_hash`` summarises
the frequency-relevant fields (top-5 categories, top-5 perspectives,
NPS, totals) for the SWOT cache key — equivalent inputs produce the
same hash, so cache invalidates on the next ingestion that meaningfully
shifts the distribution.

``business_description`` is intentionally NOT in the hash: the user can
edit it freely on /settings/profile without invalidating their cached
SWOT (the prompt re-renders fast enough that re-running through the
LLM only happens when the underlying numbers shift).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from imga_db.models import Tenant
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.analytics_service import (
    AnalyticsFilters,
    AnalyticsService,
)


@dataclass(frozen=True, slots=True)
class StrategicStatsSnapshot:
    """One-shot view of a tenant's analytics for SWOT/OKR prompts."""

    # Filter window
    date_from: date | None
    date_to: date | None

    # Tenant context (snapshot of /settings/profile values)
    industry: str | None
    industry_other_text: str | None
    company_size: str | None
    business_description: str | None

    # Headline counts
    total_reviews: int
    crisis_count: int
    sensitive_topics_count: int

    # Sentiment
    sentiment_distribution: dict[str, int]
    avg_sentiment_score: float | None

    # NPS
    nps_score: float | None
    nps_coverage_percent: float
    nps_distribution: dict[str, int]
    nps_monthly_trend: list[dict[str, Any]] = field(default_factory=list)

    # BERT primary categories (top N, ordered desc by count)
    category_distribution: list[dict[str, Any]] = field(default_factory=list)

    # Heuristic perspective (top N + the unmatched bucket)
    company_perspective_distribution: list[dict[str, Any]] = field(
        default_factory=list
    )
    unmatched_perspective_count: int = 0

    def stats_hash(self) -> str:
        """SHA-256 hex digest (first 16 chars) of the frequency-
        relevant fields. Equivalent stats produce the same hash;
        ``business_description`` + ``industry_other_text`` are
        excluded so prose edits don't invalidate the SWOT cache.

        Truncated to 16 hex chars (~64 bits) — collision risk per
        tenant is astronomical, and the cache key shape stays compact
        in Redis logs.
        """
        # Build a deterministic byte payload. JSON would work but
        # introduces ordering ambiguity for dicts; stick to a
        # hand-rolled string with a stable field order.
        parts: list[str] = []
        parts.append(f"total={self.total_reviews}")
        parts.append(f"crisis={self.crisis_count}")
        parts.append(f"sensitive={self.sensitive_topics_count}")
        # Round float fields so a 0.001 fluctuation doesn't churn the
        # cache. None → "n" so the hash distinguishes "no data" from
        # an explicit zero.
        avg = (
            f"{self.avg_sentiment_score:.3f}"
            if self.avg_sentiment_score is not None
            else "n"
        )
        nps = (
            f"{self.nps_score:.1f}"
            if self.nps_score is not None
            else "n"
        )
        parts.append(f"avg={avg}")
        parts.append(f"nps={nps}")
        parts.append(f"unmatched={self.unmatched_perspective_count}")
        # Top-5 by count for both distributions. The prompt only
        # surfaces top-5/top-7 anyway, so anything below isn't a
        # cache-relevant input.
        for entry in sorted(
            self.category_distribution[:5],
            key=lambda e: (-int(e.get("count", 0)), str(e.get("code", ""))),
        ):
            parts.append(f"cat:{entry.get('code')}:{entry.get('count')}")
        for entry in sorted(
            self.company_perspective_distribution[:5],
            key=lambda e: (-int(e.get("count", 0)), str(e.get("code", ""))),
        ):
            parts.append(f"persp:{entry.get('code')}:{entry.get('count')}")
        # Sentiment buckets — small but critical to the prompt's framing.
        for label in ("negative", "neutral", "positive"):
            parts.append(f"sent:{label}={self.sentiment_distribution.get(label, 0)}")

        payload = "|".join(parts).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


class StatsAggregator:
    """Build a ``StrategicStatsSnapshot`` for one tenant.

    Lives on an ``AsyncSession`` already bound to the tenant via
    ``bind_tenant`` so the underlying ``AnalyticsService`` reads stay
    RLS-safe. Calls six existing analytics methods (one round-trip
    each on the tenant index) — total cost is bounded by the tenant's
    review count.

    Date filter normalisation: the AnalyticsService legacy filter
    envelope wants ``datetime`` (start/end of day); the headline + NPS
    paths want ``date``. We accept ``date`` here and expand to
    datetime for the legacy envelope so callers don't have to know.
    """

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self._analytics = AnalyticsService(session)

    async def collect(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        batch_id: UUID | None = None,
    ) -> StrategicStatsSnapshot:
        # Tenant context fetched directly — we just need the four
        # 8.3.6.1-added columns; no service abstraction worth wrapping.
        tenant = await self.session.get(Tenant, self.tenant_id)
        industry = getattr(tenant, "industry", None) if tenant else None
        industry_other = (
            getattr(tenant, "industry_other_text", None) if tenant else None
        )
        company_size = (
            getattr(tenant, "company_size", None) if tenant else None
        )
        business_desc = (
            getattr(tenant, "business_description", None) if tenant else None
        )

        # Headline metrics: a single round-trip carries 6 of the 8
        # numbers we need (total, crisis, avg_sentiment, nps_score,
        # nps_coverage, sensitive_topics).
        # Sprint 9.0.5-B H — compute_headline_metrics now accepts
        # ``batch_id`` (8.3.11 documented limitation closed). When a
        # batch-scoped SWOT/OKR generates, the headline counts now
        # match the report's input universe instead of staying
        # tenant-wide, so the strategy page header no longer shows
        # 120K reviews next to a 5K-row batch SWOT.
        headline = await self._analytics.compute_headline_metrics(
            tenant_id=self.tenant_id,
            date_from=date_from,
            date_to=date_to,
            batch_id=batch_id,
        )

        # NPS detail (bucket counts) — separate from headline because
        # the headline endpoint only exposes the score + coverage.
        nps_summary = await self._analytics.compute_nps_summary(
            tenant_id=self.tenant_id,
            date_from=date_from,
            date_to=date_to,
            batch_job_id=batch_id,
        )
        nps_distribution = {
            "detractor": nps_summary.detractor_count,
            "passive": nps_summary.passive_count,
            "promoter": nps_summary.promoter_count,
        }

        # 12-month trend. Anchor on the date_to (or now) so a date-
        # filtered SWOT shows trend up to the requested window's end.
        anchor = (
            datetime.combine(date_to, datetime.min.time(), tzinfo=UTC)
            if date_to is not None
            else None
        )
        trend = await self._analytics.compute_monthly_nps_trend(
            tenant_id=self.tenant_id,
            months_back=12,
            now=anchor,
        )
        trend_payload: list[dict[str, Any]] = [
            {
                "month": p.month.isoformat(),
                "score": p.score,
                "total_count": p.total_count,
            }
            for p in trend
        ]

        # Sentiment distribution (legacy envelope wants datetime). We
        # only need the three labels normalized to lowercase keys.
        # Sprint 8.3.11 — batch_id flows through the AnalyticsFilters
        # bundle so all four downstream calls see the same scope.
        sd_filters = self._build_legacy_filters(date_from, date_to, batch_id)
        sentiment_dist = await self._analytics.sentiment_distribution(
            tenant_id=self.tenant_id, filters=sd_filters
        )
        sentiment_payload = {"negative": 0, "neutral": 0, "positive": 0}
        for row in sentiment_dist.data:
            label = row.label.upper()
            if label == "NEGATIF":
                sentiment_payload["negative"] = row.count
            elif label == "NÖTR":
                sentiment_payload["neutral"] = row.count
            elif label == "POZITIF":
                sentiment_payload["positive"] = row.count

        # BERT primary category distribution — top 10.
        cat_dist = await self._analytics.category_distribution(
            tenant_id=self.tenant_id, filters=sd_filters, limit=10
        )
        cat_payload: list[dict[str, Any]] = [
            {
                "code": row.category,
                "label_tr": row.category_label_tr,
                "count": row.count,
                "pct": row.percentage,
            }
            for row in cat_dist.data
        ]

        # Company-perspective distribution — top 10 + unmatched bucket.
        persp_dist = (
            await self._analytics.compute_company_perspective_distribution(
                tenant_id=self.tenant_id, filters=sd_filters, limit=10
            )
        )
        persp_payload: list[dict[str, Any]] = [
            {
                "code": row.code,
                "label_tr": row.label_tr,
                "count": row.count,
                "pct": row.percentage,
            }
            for row in persp_dist.data
        ]

        return StrategicStatsSnapshot(
            date_from=date_from,
            date_to=date_to,
            industry=industry,
            industry_other_text=industry_other,
            company_size=company_size,
            business_description=business_desc,
            total_reviews=headline.total_reviews,
            crisis_count=headline.crisis_count,
            sensitive_topics_count=headline.sensitive_topics_count,
            sentiment_distribution=sentiment_payload,
            avg_sentiment_score=headline.avg_sentiment_score,
            nps_score=headline.nps_score,
            nps_coverage_percent=headline.nps_coverage_percent,
            nps_distribution=nps_distribution,
            nps_monthly_trend=trend_payload,
            category_distribution=cat_payload,
            company_perspective_distribution=persp_payload,
            unmatched_perspective_count=persp_dist.unmatched_count,
        )

    @staticmethod
    def _build_legacy_filters(
        date_from: date | None,
        date_to: date | None,
        batch_id: UUID | None = None,
    ) -> AnalyticsFilters:
        """Expand date → datetime so the legacy AnalyticsFilters
        envelope (analyzed_at >= / <=) hits the right window. Same
        widening rule the headline path uses for created_at.

        Sprint 8.3.11 — accepts ``batch_id`` so SWOT/OKR generated
        with a batch scope filters every analytics call to that
        single upload's reviews.
        """
        from_dt = (
            datetime.combine(date_from, datetime.min.time(), tzinfo=UTC)
            if date_from is not None
            else None
        )
        to_dt = (
            datetime.combine(date_to, datetime.max.time(), tzinfo=UTC)
            if date_to is not None
            else None
        )
        return AnalyticsFilters(
            date_from=from_dt, date_to=to_dt, batch_job_id=batch_id,
        )
