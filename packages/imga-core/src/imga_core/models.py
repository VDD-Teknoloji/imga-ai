"""Pydantic models for analysis requests and results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SentimentLabel = Literal["NEGATIF", "NÖTR", "POZITIF"]
OverrideLayer = Literal["knowledge_base", "critical", "tier1", "sla", "tier2"]
RiskClass = Literal["NEGATIF", "NÖTR", "POZITIF"]
ClassificationMethod = Literal["keyword", "llm", "ensemble"]


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


class CategoryHit(BaseModel):
    """A single category match with confidence and matched keywords."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(..., description="Category code, e.g. 'kargo'")
    confidence: float = Field(..., ge=0.0, le=1.0)
    matched_keywords: tuple[str, ...] = Field(default_factory=tuple)


class LLMClassificationResult(BaseModel):
    """Raw output from an LLM provider (Gemini today, others later)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    primary: str = Field(..., description="Category code chosen by the LLM")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., description="One- or two-sentence justification")
    provider: str = Field(..., description="'gemini', 'claude', etc.")
    model: str = Field(..., description="Specific model name, e.g. 'gemini-2.5-flash'")
    # Sprint 9.5.5 A — captured from the SDK's usage_metadata so the
    # downstream auditor row (``llm_call_audit.input_tokens`` etc.)
    # reflects the actual call cost instead of NULL. None when the
    # provider didn't return usage info (older SDK paths, mocks).
    # Shape mirrors the SWOT/OKR token_usage dict already used in
    # GeminiProvider: {"input": int, "output": int, "total": int}.
    token_usage: dict[str, int] | None = Field(default=None)


class CategoryClassification(BaseModel):
    """Final result of category classification (keyword + optional LLM)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    primary: str = Field(..., description="Category code, e.g. 'kargo' or 'belirsiz'")
    primary_confidence: float = Field(..., ge=0.0, le=1.0)
    primary_matched_keywords: tuple[str, ...] = Field(default_factory=tuple)
    secondaries: tuple[CategoryHit, ...] = Field(default_factory=tuple)
    method: ClassificationMethod = "keyword"
    requires_manual_review: bool = Field(
        default=False,
        description="True when no classifier had high enough confidence.",
    )
    llm_result: LLMClassificationResult | None = Field(
        default=None,
        description="Set when an LLM was consulted (ensemble or llm-only path).",
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
    categorization: CategoryClassification | None = Field(
        default=None,
        description="Business-unit category (Sprint 6); set when a classifier "
        "is configured on the pipeline.",
    )
