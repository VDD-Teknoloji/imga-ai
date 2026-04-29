"""Request/response Pydantic schemas for the HTTP layer."""

from __future__ import annotations

from imga_core import AnalysisResult
from pydantic import BaseModel, ConfigDict, Field


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(..., min_length=1, max_length=10_000)


class BatchAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texts: list[str] = Field(..., min_length=1, max_length=500)


class MetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[AnalysisResult] = Field(..., min_length=1)


class HealthResponse(BaseModel):
    status: str
    version: str
    model: str
    classifier: str = Field(
        ..., description="'keyword' or 'hybrid' depending on whether an LLM is wired."
    )
    llm_available: bool = Field(
        ...,
        description="True when an LLM provider was constructed (keyword-only stack returns False).",
    )


class MetricsResponse(BaseModel):
    total: int
    shi_score: int
    crisis_count: int
    negative_rate: float
    top_bottlenecks: list[tuple[str, int]]
    alert: bool
