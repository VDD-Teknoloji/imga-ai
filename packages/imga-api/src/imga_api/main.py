"""FastAPI app: thin HTTP layer around imga-core."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from cachetools import TTLCache
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
from imga_api.middleware import RequestIDMiddleware, register_error_handlers
from imga_api.routes import auth as auth_routes
from imga_api.routes import invitations as public_invitation_routes
from imga_api.routes import metric_definitions as metric_definitions_routes
from imga_api.routes import public_trial as public_trial_routes
from imga_api.routes import tenant_action_items as tenant_action_items_routes
from imga_api.routes import tenant_analytics as tenant_analytics_routes
from imga_api.routes import tenant_analyze as tenant_analyze_routes
from imga_api.routes import tenant_batch as tenant_batch_routes
from imga_api.routes import (
    tenant_batch_progress as tenant_batch_progress_routes,
)
from imga_api.routes import (
    tenant_briefing_schedules as tenant_briefing_schedules_routes,
)
from imga_api.routes import (
    tenant_business_dimensions as tenant_business_dimensions_routes,
)
from imga_api.routes import tenant_config as tenant_config_routes
from imga_api.routes import (
    tenant_decision_audit as tenant_decision_audit_routes,
)
from imga_api.routes import tenant_directory as tenant_directory_routes
from imga_api.routes import tenant_executive as tenant_executive_routes
from imga_api.routes import (
    tenant_executive_briefings as tenant_executive_briefings_routes,
)
from imga_api.routes import tenant_insights as tenant_insights_routes
from imga_api.routes import tenant_kpi_goals as tenant_kpi_goals_routes
from imga_api.routes import tenant_llm_audit as tenant_llm_audit_routes
from imga_api.routes import tenant_llm_credentials as tenant_llm_credentials_routes
from imga_api.routes import (
    tenant_pending_webhooks as tenant_pending_webhooks_routes,
)
from imga_api.routes import tenant_profile as tenant_profile_routes
from imga_api.routes import (
    tenant_prompt_templates as tenant_prompt_templates_routes,
)
from imga_api.routes import tenant_reports as tenant_reports_routes
from imga_api.routes import tenant_reviews as tenant_reviews_routes
from imga_api.routes import tenant_sla_rules as tenant_sla_rules_routes
from imga_api.routes import (
    tenant_strategic_reports as tenant_strategic_reports_routes,
)
from imga_api.routes import tenant_taxonomies as tenant_taxonomies_routes
from imga_api.routes import tenant_trend_alerts as tenant_trend_alerts_routes
from imga_api.routes import tickets as tickets_routes
from imga_api.v1 import admin_tenants as v1_admin_tenants_routes
from imga_api.v1 import admin_tokens as v1_admin_tokens_routes
from imga_api.v1 import analyze as v1_analyze_routes
from imga_api.v1 import data as v1_data_routes
from imga_api.v1 import health as v1_health_routes
from imga_api.v1.errors import (
    PartnerApiError,
    partner_api_exception_handler,
)
from imga_api.routes.admin import invitations as admin_invitation_routes
from imga_api.routes.admin import (
    prompt_templates as admin_prompt_templates_routes,
)
from imga_api.routes.admin import tenants as admin_tenant_routes
from imga_api.schemas import (
    AnalyzeRequest,
    BatchAnalyzeRequest,
    HealthResponse,
    MetricsRequest,
    MetricsResponse,
)
from imga_api.settings import Settings, _load_dotenv

# Load .env (and .env.local override) at module import time so CORS
# origins below pick up dev defaults without a shell prefix.
_load_dotenv()


def _parse_cors_origins() -> list[str]:
    """Comma-separated IMGA_CORS_ORIGINS, or sensible dev defaults."""
    raw = os.environ.get("IMGA_CORS_ORIGINS", "").strip()
    if not raw:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]

# Sprint 9.0.5-B J — explicit project-namespace logging via the
# shared configure_logging helper. Replaces the bare basicConfig
# call so the api-worker (whose root logger is set to WARNING by
# arq) also picks up imga_core / imga_api INFO messages — without
# this, the HybridClassifier batch summary + rotator key usage
# logs dropped silently in production.
from imga_api.logging_config import configure_logging

configure_logging()
log = logging.getLogger("imga-api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    log.info("Booting imga-api %s with model=%s", __version__, settings.bert_model)
    app.state.settings = settings
    app.state.pipeline = build_pipeline(settings)
    # Sprint 9.0.5-A — arq pool is created later in this lifespan
    # (after the scheduler primitives) so routes can pick the
    # background worker path when Redis is reachable. Initialise
    # to None up front so the ``getattr(app.state, 'arq_pool',
    # None)`` checks in scheduler.enqueue_batch_job and the SSE
    # endpoint always have something to read.
    app.state.arq_pool = None
    # Per-tenant config cache (Sprint 7.4). Single-process for now;
    # Sprint 8 swaps to Redis behind the same get_tenant_config_cache
    # dependency. 5-minute TTL is short enough that audit/observability
    # gaps from out-of-band tenant edits stay bounded.
    app.state.tenant_config_cache = TTLCache(maxsize=1000, ttl=300)

    # Sprint 8.3.1 + 8.3.2 — APScheduler for batch upload + report jobs +
    # daily cleanup of both upload and report directories. Worker
    # contexts are built once and reused across job dispatches so we
    # don't reconstruct DB engines per job.
    from imga_api.workers.batch_analyzer import (
        build_worker_context,
        recover_orphans,
    )
    from imga_api.workers.report_generator import (
        build_report_context,
        recover_report_orphans,
    )
    from imga_api.workers.scheduler import (
        build_scheduler,
        schedule_cleanup,
    )

    settings.batch.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.report.reports_dir.mkdir(parents=True, exist_ok=True)
    worker_context = await build_worker_context(
        pipeline=app.state.pipeline,
        tenant_config_cache=app.state.tenant_config_cache,
        settings=settings.batch,
    )
    app.state.batch_worker_context = worker_context
    report_context = await build_report_context(settings=settings.report)
    app.state.report_worker_context = report_context

    scheduler = build_scheduler()
    app.state.batch_scheduler = scheduler

    # Recovery: PROCESSING / GENERATING jobs left in the DB came from a
    # previous process that died holding the in-memory lock. Mark them
    # failed so the UI surfaces an actionable state instead of a
    # stalled progress bar.
    orphans = await recover_orphans(worker_context)
    if orphans:
        log.warning("startup: marked %s orphaned batch jobs as failed", orphans)
    report_orphans = await recover_report_orphans(report_context)
    if report_orphans:
        log.warning("startup: marked %s orphaned report jobs as failed", report_orphans)

    schedule_cleanup(
        scheduler,
        upload_root=settings.batch.upload_dir,
        retention_hours=settings.batch.retention_hours,
    )
    schedule_cleanup(
        scheduler,
        upload_root=settings.report.reports_dir,
        retention_hours=settings.report.retention_hours,
    )
    scheduler.start()
    log.info(
        "scheduler started (upload_dir=%s, reports_dir=%s, retention=%sh)",
        settings.batch.upload_dir,
        settings.report.reports_dir,
        settings.batch.retention_hours,
    )

    # Sprint 8.3.6.5 — Redis liveness probe at startup. Non-fatal:
    # SwotService wraps every cache op in defensive try/except, so a
    # Redis blip falls through to the slow path. The startup ping is
    # purely for early observability ("did SWOT cache wire correctly
    # on this deploy?"). Skipped under tests because fakeredis is
    # injected post-lifespan via set_redis_client.
    from imga_api.cache.redis_client import get_redis_client

    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        log.info("Redis cache reachable")
    except Exception as exc:
        log.warning(
            "Redis cache not reachable at startup (%s); SWOT generation "
            "will fall through to the slow path on every call",
            exc,
        )

    # Sprint 9.0.5-A — arq pool for the api-worker container. The API
    # itself doesn't run BERT here in production (the worker
    # container does); this pool is purely for enqueueing jobs onto
    # the shared queue. Best-effort: a missed pool falls back to the
    # legacy in-process APScheduler path so the API stays writable
    # even without Redis (operationally degraded — batch jobs will
    # block the API event loop again, the very freeze this sprint
    # fixes — but at least new uploads succeed).
    try:
        from arq import create_pool

        from imga_api.workers.arq_worker import _redis_settings

        app.state.arq_pool = await create_pool(_redis_settings())
        log.info("arq batch pool ready (queue=imga-batch)")
    except Exception as exc:
        log.warning(
            "arq batch pool unavailable at startup (%s); falling "
            "back to in-process APScheduler dispatch — batch jobs "
            "will run inside the API process",
            exc,
        )
        app.state.arq_pool = None

    try:
        yield
    finally:
        log.info("Shutting down imga-api")
        scheduler.shutdown(wait=False)
        # Sprint 9.0.5-A — close the arq pool if it ever opened.
        # ``aclose`` ships on arq's ArqRedis (>=0.26); idempotent on
        # a never-opened pool because we early-return when None.
        if app.state.arq_pool is not None:
            try:
                await app.state.arq_pool.aclose()
            except Exception:
                log.exception("arq pool close failed")
            app.state.arq_pool = None
        # Dispose worker engines so asyncpg pools close cleanly.
        # In prod this is end-of-process (a no-op for behaviour); in
        # tests it's mandatory — the next test's lifespan must start
        # with no connections bound to the previous event loop.
        await worker_context.dispose()
        await report_context.dispose()
        # Sprint 8.3.6 — close the SWOT cache Redis client if it was
        # opened. Lazy: ``close_redis_client`` is a no-op when no
        # cache lookup ever ran. Same isolation reason as the worker
        # contexts: the next test's lifespan must not inherit a
        # connection bound to the previous event loop.
        from imga_api.cache.redis_client import close_redis_client

        await close_redis_client()


# OpenAPI tag metadata. Order here drives the order in Swagger UI.
# "Admin: Tenants" and "Admin: Users" are reserved for Sprint 7.5.5
# (super-admin tenant + invitation HTTP routes); they appear in the
# spec without endpoints today so the frontend has a stable contract
# to plan against.
_OPENAPI_TAGS = [
    {"name": "Auth", "description": "Authentication, JWT rotation, password change."},
    {"name": "Admin: Tenants", "description": "Super-admin tenant CRUD (Sprint 7.5.5)."},
    {"name": "Admin: Users", "description": "Super-admin user CRUD + invitations (Sprint 7.5.5)."},
    {"name": "Tenant Config", "description": "Per-tenant settings, taxonomy, automation mode."},
    {"name": "Tenant Directory", "description": "Active members of the current tenant (assignee picker, etc.)."},
    {"name": "Analyze", "description": "Sentiment + categorization pipeline."},
    {"name": "Tickets", "description": "Ticket CRUD and lifecycle transitions."},
    {"name": "Health", "description": "Service health and readiness probes."},
]

_API_DESCRIPTION = """
HTTP API for imga.AI — Turkish customer-review sentiment platform.

Authentication: send `Authorization: Bearer <access_token>` on every
non-public endpoint. Tokens are issued by `POST /auth/login` and
rotated through `POST /auth/refresh`. The refresh token is single-use:
each rotation invalidates the previous one. Replaying a consumed
refresh token revokes the entire session family.

Tenant context: tenant-scoped endpoints read `active_tenant_id` from
the JWT and enforce row-level security against
`current_setting('app.current_tenant_id')`. To switch tenants, call
`POST /auth/switch-tenant`.
""".strip()

app = FastAPI(
    title="imga.AI API",
    version=__version__,
    description=_API_DESCRIPTION,
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,
)

# Rate limiting is applied via FastAPI Depends on individual routes
# (see imga_api/rate_limit.py + routes/invitations.py). We don't use
# slowapi's decorator pattern because functools.wraps over the route
# handler breaks FastAPI's Annotated-Depends introspection; the
# Depends-based limiter sidesteps that and stays in pure FastAPI idiom.

# CORS — dev frontend lives on a different origin (:3000 vs :8003).
# Production uses the same origin (proxied by Caddy in Sprint 8) so
# this middleware is largely a no-op in prod, but the explicit allow-
# list keeps the security boundary visible.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    # Sprint 9.1 C — expose X-Request-ID so the browser can read the
    # response header on cross-origin XHR (api-client surfaces it as
    # ApiError.requestId for support tickets).
    expose_headers=["*", "X-Request-ID"],
)

# Sprint 9.1 C — request_id middleware MUST be added after CORS so it
# wraps every request including the OPTIONS preflight (Starlette
# evaluates middlewares last-added-first; outermost wraps innermost).
# The 5xx handler is registered as an exception_handler (not a
# middleware) so its order relative to others doesn't matter.
app.add_middleware(RequestIDMiddleware)
register_error_handlers(app)
app.add_exception_handler(PartnerApiError, partner_api_exception_handler)

app.include_router(auth_routes.router)
app.include_router(v1_admin_tokens_routes.router)
app.include_router(v1_admin_tenants_routes.router)
app.include_router(v1_analyze_routes.router)
app.include_router(v1_data_routes.router)
app.include_router(v1_health_routes.router)
app.include_router(tenant_config_routes.router)
app.include_router(tenant_analyze_routes.router)
app.include_router(tenant_batch_routes.router)
app.include_router(tenant_batch_progress_routes.router)
app.include_router(tenant_reviews_routes.router)
app.include_router(tenant_reports_routes.router)
app.include_router(tenant_analytics_routes.router)
# Sprint 10.0 — C-level dashboard tek-bakış aggregate'i.
app.include_router(tenant_executive_routes.router)
app.include_router(tenant_directory_routes.router)
app.include_router(tenant_taxonomies_routes.router)
app.include_router(tenant_sla_rules_routes.router)
app.include_router(tenant_insights_routes.router)
app.include_router(tenant_executive_briefings_routes.router)
app.include_router(tenant_briefing_schedules_routes.router)
app.include_router(tenant_action_items_routes.router)
app.include_router(tenant_kpi_goals_routes.router)
app.include_router(tenant_trend_alerts_routes.router)
app.include_router(tickets_routes.router)
# Sprint 8.3.6.5 — strategic reports + LLM credentials + tenant profile.
app.include_router(tenant_profile_routes.router)
app.include_router(tenant_llm_credentials_routes.router)
app.include_router(tenant_strategic_reports_routes.router)
app.include_router(tenant_pending_webhooks_routes.router)
app.include_router(admin_tenant_routes.router)
app.include_router(admin_invitation_routes.router)
app.include_router(admin_prompt_templates_routes.router)
app.include_router(public_invitation_routes.router)
# Sprint 9.7 — imga.ai marketing-site trial proxy.
app.include_router(public_trial_routes.router)
# Sprint 9.2 A — public KPI metric registry.
app.include_router(metric_definitions_routes.router)
# Sprint 9.3 — governance + dimensions + decisions + prompt templates.
app.include_router(tenant_llm_audit_routes.router)
app.include_router(tenant_decision_audit_routes.router)
app.include_router(tenant_business_dimensions_routes.router)
app.include_router(tenant_prompt_templates_routes.router)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Service health probe (no auth required).",
)
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


# Sprint 9.0.6 D — legacy public demo endpoints. Pre-tenant-scoped
# surface (/analyze, /analyze/batch, /classify, /metrics); kept
# behind a default-off env flag so production servers 404 these
# paths until an integration explicitly opts in. The tenant-scoped
# /tenants/me/analyze stays unconditionally registered above.
from fastapi import APIRouter as _LegacyAPIRouter

_legacy_router = _LegacyAPIRouter()


@_legacy_router.post(
    "/analyze",
    response_model=AnalysisResult,
    tags=["Analyze"],
    summary="Run sentiment + categorization on a single text.",
    description=(
        "Returns sentiment label (POZITIF / NEGATIF / NÖTR), confidence, "
        "primary category, secondary categories, and any rule hits "
        "(e.g. SLA breach signals). Legacy public surface — gated on "
        "``IMGA_ENABLE_PUBLIC_DEMO_ENDPOINTS=true`` (default false)."
    ),
)
def analyze(
    body: AnalyzeRequest,
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
) -> AnalysisResult:
    return pipeline.analyze(body.text)


@_legacy_router.post(
    "/analyze/batch",
    response_model=list[AnalysisResult],
    tags=["Analyze"],
    summary="Batch variant of /analyze.",
)
def analyze_batch(
    body: BatchAnalyzeRequest,
    pipeline: Annotated[AnalysisPipeline, Depends(get_pipeline)],
) -> list[AnalysisResult]:
    return pipeline.analyze_batch(body.texts)


@_legacy_router.post(
    "/classify",
    response_model=CategoryClassification,
    tags=["Analyze"],
    summary="Category-only path. Skips BERT sentiment, ~10x faster than /analyze.",
)
def classify(
    body: AnalyzeRequest,
    classifier: Annotated[CategoryClassifier, Depends(get_classifier)],
) -> CategoryClassification:
    return classifier.classify(body.text)


@_legacy_router.post(
    "/metrics",
    response_model=MetricsResponse,
    tags=["Analyze"],
    summary="Executive metrics (SHI score, crisis count, negative rate) over a result set.",
)
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


# Sprint 9.0.6 D — gate the legacy router. Settings.from_env reads
# IMGA_ENABLE_PUBLIC_DEMO_ENDPOINTS before route registration runs;
# the conditional wires the router only when the deploy explicitly
# opts in.
if Settings.from_env().enable_public_demo_endpoints:
    app.include_router(_legacy_router)
    log.warning(
        "IMGA_ENABLE_PUBLIC_DEMO_ENDPOINTS=true — legacy public "
        "/analyze, /analyze/batch, /classify, /metrics endpoints "
        "are exposed without authentication.",
    )
