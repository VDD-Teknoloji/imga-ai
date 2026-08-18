"""Threshold-based KPI deviation detector.

Sprint 8.3.10. Three rules this sprint, all comparing the current
window vs the prior window of the same length:

  * ``nps_drop_week``               — week-over-week NPS drop
                                      severity warning
  * ``negative_sentiment_jump``     — week-over-week negative-share
                                      jump ≥ 10 percentage points →
                                      severity warning
  * ``review_volume_spike``         — current week volume ≥ 200% of
                                      4-week trailing average →
                                      severity info

The service produces ``TrendAlert`` model rows but does NOT persist
— the caller (route layer) adds them to its session inside the same
transaction so RLS binds correctly. That keeps the service pure and
testable without a DB fixture.

Sprint 8.6 will wrap this in a cron driver; the service itself
needs no changes for that.

Sprint 9.0.5-B updates:
  E — NPS now uses the canonical ``AnalyticsService.compute_nps_summary``
      (-100..100 scale, promoter%-detractor%) instead of the raw
      0-10 ``func.avg(nps_score)``. The drop threshold rescales
      from 1.5 (raw points) to 10 (canonical points) to match.
  I — Each alert carries a ``fingerprint`` so the daily UNIQUE
      index in migration 0024 keeps the same condition from
      spamming repeat rows on every ``/evaluate`` call. Service
      filters out alerts whose fingerprint already landed today;
      the index is the race-safety net.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from imga_db.models import Review, TrendAlert
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


# Sprint 9.0.5-B E — was 1.5 on the raw 0-10 scale; now 10 on the
# canonical -100..100 scale. A week-over-week drop of 10 NPS points
# is a meaningful deterioration without being noisy.
_NPS_DROP_THRESHOLD = 10.0
_NEG_JUMP_THRESHOLD_PP = 10.0
_VOLUME_SPIKE_RATIO = 2.0


@dataclass(frozen=True)
class _WindowStats:
    review_count: int
    nps_score: float | None
    negative_share: float


class TrendAlertService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate(self, *, tenant_id: UUID) -> list[TrendAlert]:
        """Compute the three rules and return one ``TrendAlert`` per
        breach. Caller persists.

        Sprint 9.0.5-B I — return value is filtered against today's
        already-persisted fingerprints so a re-run inside the same
        UTC day doesn't append duplicates. Migration 0024's partial
        UNIQUE index is the race-safe backstop for concurrent
        ``/evaluate`` invocations.

        Windows compared:
          * NPS / negative-share: current 7 days vs prior 7 days
          * Volume spike: current 7 days vs avg of prior four 7-day
            windows
        """
        try:
            now = datetime.now(UTC)
            current = await self._stats(
                tenant_id, now - timedelta(days=7), now
            )
            prior = await self._stats(
                tenant_id,
                now - timedelta(days=14),
                now - timedelta(days=7),
            )
            trailing_volumes = [
                (await self._stats(
                    tenant_id,
                    now - timedelta(days=7 * (i + 2)),
                    now - timedelta(days=7 * (i + 1)),
                )).review_count
                for i in range(4)
            ]
        except Exception:
            _logger.exception(
                "trend_alert evaluate failed",
                extra={"tenant_id": str(tenant_id)},
            )
            raise

        candidates: list[TrendAlert] = []

        # Rule 1: NPS drop. Sprint 9.0.5-B E — canonical scale.
        if (
            current.nps_score is not None
            and prior.nps_score is not None
            and prior.nps_score - current.nps_score >= _NPS_DROP_THRESHOLD
        ):
            fp = _fingerprint(
                "nps_drop_week", now,
                f"prior={prior.nps_score:.0f}",
                f"current={current.nps_score:.0f}",
            )
            candidates.append(
                TrendAlert(
                    tenant_id=tenant_id,
                    alert_type="nps_drop_week",
                    severity="warning",
                    title="NPS skoru bir hafta içinde düştü",
                    description=(
                        f"NPS bu hafta {current.nps_score:.1f}; geçen hafta "
                        f"{prior.nps_score:.1f}. "
                        f"{prior.nps_score - current.nps_score:.1f} puanlık "
                        "düşüş eşiği aşıldı."
                    ),
                    evidence={
                        "current": current.nps_score,
                        "previous": prior.nps_score,
                        "delta": current.nps_score - prior.nps_score,
                        "threshold": -_NPS_DROP_THRESHOLD,
                        "scale": "canonical_-100_to_100",
                    },
                    fingerprint=fp,
                )
            )

        # Rule 2: negative-share jump.
        delta_pp = (current.negative_share - prior.negative_share) * 100
        if delta_pp >= _NEG_JUMP_THRESHOLD_PP:
            fp = _fingerprint(
                "negative_sentiment_jump", now,
                f"delta_pp={delta_pp:.1f}",
            )
            candidates.append(
                TrendAlert(
                    tenant_id=tenant_id,
                    alert_type="negative_sentiment_jump",
                    severity="warning",
                    title="Negatif yorum oranı sıçradı",
                    description=(
                        f"Bu hafta negatif yorum oranı %{current.negative_share * 100:.1f}; "
                        f"geçen hafta %{prior.negative_share * 100:.1f}. "
                        f"+{delta_pp:.1f}pp eşiği aşıldı."
                    ),
                    evidence={
                        "current_share": current.negative_share,
                        "previous_share": prior.negative_share,
                        "delta_pp": delta_pp,
                        "threshold_pp": _NEG_JUMP_THRESHOLD_PP,
                    },
                    fingerprint=fp,
                )
            )

        # Rule 3: volume spike.
        if trailing_volumes:
            avg_trailing = sum(trailing_volumes) / len(trailing_volumes)
            if (
                avg_trailing > 0
                and current.review_count >= avg_trailing * _VOLUME_SPIKE_RATIO
            ):
                fp = _fingerprint(
                    "review_volume_spike", now,
                    f"current={current.review_count}",
                )
                candidates.append(
                    TrendAlert(
                        tenant_id=tenant_id,
                        alert_type="review_volume_spike",
                        severity="info",
                        title="Yorum hacminde ani artış",
                        description=(
                            f"Bu hafta {current.review_count} yorum; "
                            f"4 hafta ortalaması {avg_trailing:.1f}. "
                            f"%{(current.review_count / avg_trailing) * 100:.0f} "
                            "seviyesinde sıçrama."
                        ),
                        evidence={
                            "current_volume": current.review_count,
                            "trailing_avg": avg_trailing,
                            "ratio": (
                                current.review_count / avg_trailing
                                if avg_trailing > 0
                                else None
                            ),
                            "threshold_ratio": _VOLUME_SPIKE_RATIO,
                        },
                        fingerprint=fp,
                    )
                )

        return await self._filter_already_emitted_today(
            tenant_id, candidates, now,
        )

    async def _filter_already_emitted_today(
        self,
        tenant_id: UUID,
        candidates: list[TrendAlert],
        now: datetime,
    ) -> list[TrendAlert]:
        """Sprint 9.0.5-B I — drop candidates whose fingerprint
        already landed today. Single SELECT per evaluate call;
        the per-day UNIQUE INDEX in migration 0024 catches any
        race that slips between this read and the route's flush."""
        if not candidates:
            return []
        fingerprints = {a.fingerprint for a in candidates if a.fingerprint}
        if not fingerprints:
            return candidates
        day_start = datetime(now.year, now.month, now.day)
        day_end = day_start + timedelta(days=1)
        stmt = (
            select(TrendAlert.fingerprint)
            .where(TrendAlert.tenant_id == tenant_id)
            .where(TrendAlert.fingerprint.in_(fingerprints))
            .where(TrendAlert.evaluated_at >= day_start)
            .where(TrendAlert.evaluated_at < day_end)
        )
        existing = {
            r[0] for r in (await self._session.execute(stmt)).all()
        }
        if existing:
            _logger.info(
                "trend_alert evaluate: %d duplicate fingerprint(s) "
                "skipped (already emitted today)",
                len(existing),
                extra={"tenant_id": str(tenant_id)},
            )
        return [a for a in candidates if a.fingerprint not in existing]

    async def _stats(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> _WindowStats:
        # Sprint 9.0.5-B E — canonical NPS via the shared
        # AnalyticsService.compute_nps_summary path. The previous
        # ``func.avg(Review.nps_score)`` produced a 0-10 number that
        # callers misread as NPS; the dashboard, executive briefing,
        # and trend alerts now share one definition (-100..100).
        from imga_api.services.analytics_service import AnalyticsService

        analytics = AnalyticsService(self._session)
        nps_summary = await analytics.compute_nps_summary(
            tenant_id=tenant_id,
            date_from=start.date(),
            date_to=end.date(),
        )

        stmt = select(
            func.count().label("cnt"),
            func.sum(
                case(
                    (Review.sentiment_label == "NEGATIF", 1),
                    else_=0,
                )
            ).label("neg_count"),
        ).where(
            Review.tenant_id == tenant_id,
            Review.deleted_at.is_(None),
            Review.review_date >= start,
            Review.review_date < end,
            # 2026-08-18 — trend eşikleri de temiz veriden hesaplanır;
            # bir bayraklı-yorum yığını yanlış bir "hacim sıçraması"
            # ya da "negatif sıçrama" alarmı tetiklemesin.
            Review.quality_flag.is_(None),
        )
        row = (await self._session.execute(stmt)).one()
        cnt = int(row.cnt or 0)
        neg = int(row.neg_count or 0)
        share = (neg / cnt) if cnt > 0 else 0.0
        return _WindowStats(
            review_count=cnt,
            nps_score=nps_summary.score,
            negative_share=share,
        )


def _fingerprint(alert_type: str, now: datetime, *parts: str) -> str:
    """Stable hash for the dedupe index. Sprint 9.0.5-B I.

    Ingredients:
      * ``alert_type`` — distinguish rules from each other.
      * Calendar week (ISO year-week) — same condition fires once
        per week even if the rolling 7-day window slides; aligns
        with the rules' natural cadence.
      * Rule-specific quantised inputs (``parts``) — e.g. NPS
        rounded to integer so a ±0.4 jitter doesn't bypass the
        dedupe.

    Output: 64-char hex (SHA-256 first 32 bytes); fits the
    String(64) column without escaping.
    """
    iso_year, iso_week, _ = now.isocalendar()
    payload = "|".join(
        [alert_type, f"{iso_year}-W{iso_week:02d}", *parts]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__: list[Any] = ["TrendAlertService"]
