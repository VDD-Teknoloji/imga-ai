"""FastAPI app: thin HTTP layer around imga-core."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from imga_core import AnalysisPipeline, AnalysisResult
from imga_core.metrics import calculate_executive_metrics, is_alert_state

from imga_api import __version__
from imga_api.dependencies import build_pipeline, get_pipeline, get_settings
from imga_api.schemas import (
    AnalyzeRequest,
    BatchAnalyzeRequest,
    HealthResponse,
    MetricsRequest,
    MetricsResponse,
)
from imga_api.settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("imga-api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    log.info("Booting imga-api %s with model=%s", __version__, settings.bert_model)
    app.state.settings = settings
    app.state.pipeline = build_pipeline(settings)
    yield
    log.info("Shutting down imga-api")


app = FastAPI(
    title="imga-api",
    version=__version__,
    description="HTTP wrapper around imga-core sentiment pipeline.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, model=settings.bert_model)


@app.post("/analyze", response_model=AnalysisResult)
def analyze(
    body: AnalyzeRequest,
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
) -> AnalysisResult:
    return pipeline.analyze(body.text)


@app.post("/analyze/batch", response_model=list[AnalysisResult])
def analyze_batch(
    body: BatchAnalyzeRequest,
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
) -> list[AnalysisResult]:
    return pipeline.analyze_batch(body.texts)


@app.post("/metrics", response_model=MetricsResponse)
def metrics(body: MetricsRequest) -> MetricsResponse:
    m = calculate_executive_metrics(body.results)
    return MetricsResponse(
        total=m.total,
        shi_score=m.shi_score,
        crisis_count=m.crisis_count,
        negative_rate=m.negative_rate,
        top_bottlenecks=m.top_bottlenecks,
        alert=is_alert_state(body.results),
    )
