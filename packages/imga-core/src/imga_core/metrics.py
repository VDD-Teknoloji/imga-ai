"""Aggregate executive metrics over a list of AnalysisResults.

Pure functions, deterministic. No DataFrame coupling — accept
list[AnalysisResult] and return primitive values or dicts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from imga_core.config import (
    CRISIS_SCORE_THRESHOLD,
    HIGH_NEGATIVE_RATE,
    LABEL_NEGATIVE,
    LABEL_NEUTRAL,
    LABEL_POSITIVE,
    SHI_NEUTRAL_WEIGHT,
    SHI_POSITIVE_WEIGHT,
    TOP_BOTTLENECKS_N,
)
from imga_core.models import AnalysisResult


@dataclass(frozen=True, slots=True)
class ExecutiveMetrics:
    """Top-level KPIs for the executive summary panel."""

    total: int
    shi_score: int
    crisis_count: int
    negative_rate: float
    top_bottlenecks: list[tuple[str, int]]


def calculate_shi(results: Iterable[AnalysisResult]) -> int:
    """Compute the Sentiment Health Index.

    SHI = (POZITIF% * SHI_POSITIVE_WEIGHT) + (NÖTR% * SHI_NEUTRAL_WEIGHT)

    Returns 0 when no results.
    """
    total = pos = neu = 0
    for r in results:
        total += 1
        if r.sentiment_label == LABEL_POSITIVE:
            pos += 1
        elif r.sentiment_label == LABEL_NEUTRAL:
            neu += 1
    if total == 0:
        return 0
    score = (pos / total) * SHI_POSITIVE_WEIGHT + (neu / total) * SHI_NEUTRAL_WEIGHT
    return int(score)


def count_crises(results: Iterable[AnalysisResult]) -> int:
    """Count results whose sentiment_score is at or below the crisis threshold."""
    return sum(1 for r in results if r.sentiment_score <= CRISIS_SCORE_THRESHOLD)


def negative_rate(results: Iterable[AnalysisResult]) -> float:
    """Fraction of NEGATIF results, in [0.0, 1.0]."""
    total = neg = 0
    for r in results:
        total += 1
        if r.sentiment_label == LABEL_NEGATIVE:
            neg += 1
    return neg / total if total else 0.0


def top_bottlenecks(
    results: Iterable[AnalysisResult],
    n: int = TOP_BOTTLENECKS_N,
) -> list[tuple[str, int]]:
    """Return the N most-common company_perspective values among NEGATIF results."""
    counter: Counter[str] = Counter()
    for r in results:
        if r.sentiment_label != LABEL_NEGATIVE:
            continue
        if r.company_perspective:
            counter[r.company_perspective] += 1
    return counter.most_common(n)


def calculate_executive_metrics(results: list[AnalysisResult]) -> ExecutiveMetrics:
    """Bundle SHI / crisis / bottlenecks / negative-rate into one struct."""
    return ExecutiveMetrics(
        total=len(results),
        shi_score=calculate_shi(results),
        crisis_count=count_crises(results),
        negative_rate=negative_rate(results),
        top_bottlenecks=top_bottlenecks(results),
    )


def is_alert_state(results: list[AnalysisResult]) -> bool:
    """True when negative rate exceeds the alert threshold."""
    return negative_rate(results) > HIGH_NEGATIVE_RATE
