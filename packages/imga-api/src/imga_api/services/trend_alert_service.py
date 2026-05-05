"""Threshold-based KPI deviation detector.

Sprint 8.3.10. Three rules this sprint, all comparing the current
window vs the prior window of the same length:

  * ``nps_drop_week``               — week-over-week NPS drop ≥ 1.5
                                      points → severity warning
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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from imga_db.models import Review, TrendAlert
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


_NPS_DROP_THRESHOLD = 1.5
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

        Windows compared:
          * NPS / negative-share: current 7 days vs prior 7 days
          * Volume spike: current 7 days vs avg of prior four 7-day
            windows
        """
        try:
            now = datetime.utcnow()
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

        out: list[TrendAlert] = []

        # Rule 1: NPS drop.
        if (
            current.nps_score is not None
            and prior.nps_score is not None
            and prior.nps_score - current.nps_score >= _NPS_DROP_THRESHOLD
        ):
            out.append(
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
                    },
                )
            )

        # Rule 2: negative-share jump.
        delta_pp = (current.negative_share - prior.negative_share) * 100
        if delta_pp >= _NEG_JUMP_THRESHOLD_PP:
            out.append(
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
                )
            )

        # Rule 3: volume spike.
        if trailing_volumes:
            avg_trailing = sum(trailing_volumes) / len(trailing_volumes)
            if (
                avg_trailing > 0
                and current.review_count >= avg_trailing * _VOLUME_SPIKE_RATIO
            ):
                out.append(
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
                    )
                )

        return out

    async def _stats(
        self,
        tenant_id: UUID,
        start: datetime,
        end: datetime,
    ) -> _WindowStats:
        stmt = select(
            func.count().label("cnt"),
            func.avg(Review.nps_score).label("nps_avg"),
            func.sum(
                case(
                    (Review.sentiment_label == "NEGATIF", 1),
                    else_=0,
                )
            ).label("neg_count"),
        ).where(
            Review.tenant_id == tenant_id,
            Review.deleted_at.is_(None),
            Review.created_at >= start,
            Review.created_at < end,
        )
        row = (await self._session.execute(stmt)).one()
        cnt = int(row.cnt or 0)
        neg = int(row.neg_count or 0)
        nps = float(row.nps_avg) if row.nps_avg is not None else None
        share = (neg / cnt) if cnt > 0 else 0.0
        return _WindowStats(
            review_count=cnt, nps_score=nps, negative_share=share
        )


__all__: list[Any] = ["TrendAlertService"]
