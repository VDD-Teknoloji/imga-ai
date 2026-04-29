"""Pydantic models for analysis requests and results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SentimentLabel = Literal["NEGATIF", "NÖTR", "POZITIF"]
OverrideLayer = Literal["knowledge_base", "critical", "tier1", "sla", "tier2"]
RiskClass = Literal["NEGATIF", "NÖTR", "POZITIF"]


class AnalysisRequest(BaseModel):
    """Single review submitted for analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(..., description="Raw review text (may be multi-line).")
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional metadata such as channel, source, timestamp.",
    )


class OverrideHit(BaseModel):
    """One override layer fired for a given input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    layer: OverrideLayer
    matched_keywords: list[str] = Field(default_factory=list)
    score: float = Field(
        ...,
        description="Sentiment score assigned by this override (range -1.0 to 1.0).",
    )
    detail: str | None = Field(
        default=None,
        description="Optional human-readable explanation (e.g. 'SLA exceeded: 5 days > 3').",
    )


class AnalysisResult(BaseModel):
    """Full analysis output for a single review."""

    model_config = ConfigDict(extra="forbid")

    text: str
    sentiment_label: SentimentLabel
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    overrides_applied: list[OverrideHit] = Field(default_factory=list)
    summary: str | None = None
    customer_perspective: str | None = None
    company_perspective: str | None = None
    risk_class: RiskClass | None = None
    sla_detected: str | None = Field(
        default=None,
        description="SLA status string when a duration was detected, e.g. 'SLA Aşımı (5 Gün > 3)'.",
    )
