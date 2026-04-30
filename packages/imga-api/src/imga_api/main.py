"""FastAPI app: thin HTTP layer around imga-core."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from cachetools import TTLCache
from fastapi import Depends, FastAPI
from imga_core import (
    AnalysisPipeline,
    AnalysisResult,
    CategoryClassification,
    CategoryClassifier,
    HybridClassifier,
)
from imga_core.metrics import calculate_executive_metrics, is_alert_state

from imga_api import __version__
from imga_api.dependencies import (
    build_pipeline,
    get_classifier,
    get_pipeline,
    get_settings,
)
from imga_api.routes import auth as auth_routes
from imga_api.routes import tenant_config as tenant_config_routes
from imga_api.routes import tickets as tickets_routes
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
    # Per-tenant config cache (Sprint 7.4). Single-process for now;
    # Sprint 8 swaps to Redis behind the same get_tenant_config_cache
    # dependency. 5-minute TTL is short enough that audit/observability
    # gaps from out-of-band tenant edits stay bounded.
    app.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)
    yield
    log.info("Shutting down imga-api")


app = FastAPI(
    title="imga-api",
    version=__version__,
    description="HTTP wrapper around imga-core sentiment + categorization pipeline.",
    lifespan=lifespan,
)

app.include_router(auth_routes.router)
app.include_router(tenant_config_routes.router)
app.include_router(tickets_routes.router)


@app.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
) -> HealthResponse:
    classifier = pipeline.classifier
    classifier_kind = "hybrid" if isinstance(classifier, HybridClassifier) else "keyword"
    llm_available = isinstance(classifier, HybridClassifier) and classifier.llm is not None
    return HealthResponse(
        status="ok",
        version=__version__,
        model=settings.bert_model,
        classifier=classifier_kind,
        llm_available=llm_available,
    )


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


@app.post("/classify", response_model=CategoryClassification)
def classify(
    body: AnalyzeRequest,
    classifier: Annotated[CategoryClassifier, Depends(get_classifier)],
) -> CategoryClassification:
    """Category-only path. Skips BERT sentiment, ~10x faster than /analyze."""
    return classifier.classify(body.text)


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
