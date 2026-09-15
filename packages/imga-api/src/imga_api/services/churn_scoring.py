"""Explainable prioritisation rules; scores are NOT churn probabilities."""

from __future__ import annotations

from datetime import date

from imga_api.services.intelligence_schemas import (
    CustomerProfile,
    CustomerRisk,
    ReviewSignals,
    RiskSignal,
)


def score_customer(
    profile: CustomerProfile, reviews: ReviewSignals, *, as_of: date
) -> CustomerRisk:
    signals: list[RiskSignal] = []
    missing: list[str] = []
    domains = 0
    if profile.lifecycle != "active":
        return CustomerRisk(
            as_of=as_of,
            score=None,
            band="inactive",
            data_status="inactive",
            observed_domains=0,
            signals=[],
            missing=[],
            review_signals=reviews,
        )
    if not 0 <= (as_of - profile.observed_on).days <= 14:
        return CustomerRisk(
            as_of=as_of,
            score=None,
            band="unknown",
            data_status="stale",
            observed_domains=0,
            signals=[],
            missing=["fresh_observation"],
            review_signals=reviews,
        )

    def add(code: str, points: int, evidence: str, recommendation: str) -> None:
        signals.append(
            RiskSignal(code=code, points=points, evidence=evidence, recommendation=recommendation)
        )

    if profile.cancellation_requested is not None:
        domains += 1
        if profile.cancellation_requested:
            add(
                "cancellation",
                60,
                "Kaynak sistemde açık iptal talebi var.",
                "Hesap sorumlusu iptal nedenini müşteriyle doğrulasın.",
            )
    else:
        missing.append("cancellation_requested")
    behavior_points = 0
    behavior_evidence: list[str] = []
    has_behavior = False
    for name, current, previous, minimum in (
        ("Sipariş", profile.orders_current_30d, profile.orders_previous_30d, 3),
        ("Kullanım", profile.usage_current_30d, profile.usage_previous_30d, 5),
    ):
        if current is not None and previous is not None and previous >= minimum:
            has_behavior = True
            drop = 1 - current / previous
            if drop >= 0.5:
                behavior_points = min(35, behavior_points + 25)
                behavior_evidence.append(
                    f"{name}: önceki 30 gün {previous}, son 30 gün {current} (%{drop * 100:.0f} düşüş)"
                )
    if has_behavior:
        domains += 1
    else:
        missing.append("comparable_behavior_windows")
    if behavior_points:
        add(
            "behavior_drop",
            behavior_points,
            "; ".join(behavior_evidence),
            "Mevsimsellik, kesinti ve hesap değişimini doğrulayın; neden görüşmesi planlayın.",
        )
    if profile.last_activity_on is not None and profile.expected_activity_days is not None:
        domains += 1
        # Observation-time, not wall-clock, prevents an old snapshot inventing inactivity.
        inactive_days = (profile.observed_on - profile.last_activity_on).days
        if inactive_days >= 2 * profile.expected_activity_days:
            add(
                "inactivity",
                20,
                f"{inactive_days} gündür aktivite yok; beklenen aralık {profile.expected_activity_days} gün.",
                "Kanalın veri akışını doğrulayın, hesap sorumlusuna takip atayın.",
            )
    else:
        missing.append("activity_baseline")
    if profile.overdue_invoices is not None:
        domains += 1
        if profile.overdue_invoices > 0:
            add(
                "overdue",
                20,
                f"{profile.overdue_invoices} vadesi geçmiş fatura.",
                "Faturalama ihtilafı ile ödeme gecikmesini ayırın.",
            )
    else:
        missing.append("overdue_invoices")
    if reviews.total >= 3:
        domains += 1
        if reviews.negative >= 3 and reviews.negative / reviews.total >= 0.5:
            add(
                "repeat_complaints",
                15,
                f"Son 30 günde {reviews.total} yorumun {reviews.negative} adedi olumsuz.",
                "Tekrarlayan konuları ve açık destek kayıtlarını inceleyin.",
            )
        if reviews.sla_violations >= 2:
            add(
                "sla",
                10,
                f"Son 30 günde {reviews.sla_violations} çözüm SLA ihlali.",
                "Süreç sahibine çözüm planı ve müşteri bilgilendirme görevi verin.",
            )
        if reviews.low_nps >= 2:
            add(
                "nps",
                10,
                f"Son 30 günde {reviews.low_nps} detractor yanıtı.",
                "Memnuniyetsizlik nedenini doğrulayın; indirim teklifini otomatikleştirmeyin.",
            )
    else:
        missing.append("linked_review_history")
    points = min(100, sum(signal.points for signal in signals))
    if profile.renewal_on and 0 <= (profile.renewal_on - as_of).days <= 30 and points > 0:
        add(
            "renewal",
            10,
            f"Yenileme tarihi {profile.renewal_on.isoformat()}.",
            "Yenileme görüşmesini mevcut sorunlar için çözüm planıyla birlikte yapın.",
        )
        points = min(100, points + 10)
    sufficient = domains >= 2 or profile.cancellation_requested is True
    band = "unknown"
    if sufficient:
        band = (
            "critical"
            if points >= 60
            else "high"
            if points >= 40
            else "watch"
            if points >= 20
            else "low"
        )
    return CustomerRisk.model_validate(
        {
            "as_of": as_of,
            "score": points if sufficient else None,
            "band": band,
            "data_status": "sufficient" if sufficient else "insufficient",
            "observed_domains": domains,
            "signals": signals,
            "missing": missing,
            "review_signals": reviews,
        }
    )
