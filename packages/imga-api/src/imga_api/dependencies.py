"""FastAPI dependency providers — singleton pipeline kept on app.state."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from cachetools import TTLCache
from fastapi import Depends, Request
from imga_core import (
    AnalysisPipeline,
    BertSentimentAnalyzer,
    CategoryClassifier,
    HybridClassifier,
    KeywordCategoryClassifier,
    SLAParams,
    create_llm_provider,
)
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.db_deps import get_app_session
from imga_api.services import (
    AuditService,
    CommentService,
    ReviewService,
    TenantConfigService,
    TicketService,
)
from imga_api.settings import Settings


def build_classifier() -> CategoryClassifier:
    """Construct the category classifier from environment.

    Always returns a usable classifier:
      - Keyword-only when no LLM is configured
      - Hybrid (keyword + LLM) when GEMINI_API_KEY + IMGA_LLM_FALLBACK_ENABLED=true
    """
    keyword = KeywordCategoryClassifier()
    llm = create_llm_provider()
    if llm is None:
        return keyword
    return HybridClassifier(keyword_classifier=keyword, llm_provider=llm)


def build_sentiment_analyzer(settings: Settings) -> Any:
    """Sprint 11.0 — sentiment fallback zinciri.

    Birincil sınıflandırma artık Gemini unified'dan (worker tarafında);
    bu analyzer zinciri yalnızca unified üretemediğinde devreye girer:

      1. Uzak BERT (Modal) — IMGA_REMOTE_BERT_URL ayarlıysa. VPS'e
         model yüklenmez, RAM/CPU baskısı sıfır.
      2. Lokal BERT (lazy) — son çare; model image'a artık bake
         edilmediği için İLK kullanımda HF Hub'dan iner.
    """
    import os

    from imga_core.analyzers.chained import ChainedSentimentAnalyzer
    from imga_core.analyzers.remote_http import RemoteHTTPSentimentAnalyzer

    local = BertSentimentAnalyzer(model_name=settings.bert_model)
    remote_url = os.environ.get("IMGA_REMOTE_BERT_URL", "").strip()
    if not remote_url:
        return local
    remote = RemoteHTTPSentimentAnalyzer(
        remote_url,
        token=os.environ.get("IMGA_REMOTE_BERT_TOKEN") or None,
    )
    return ChainedSentimentAnalyzer(
        [("remote-modal", remote), ("local-bert", local)]
    )


def build_pipeline(settings: Settings) -> AnalysisPipeline:
    """Construct the pipeline. Called once at startup."""
    return AnalysisPipeline(
        analyzer=build_sentiment_analyzer(settings),
        knowledge_base_path=settings.knowledge_base_path,
        rules_path=settings.rules_path,
        sla_params=SLAParams(
            max_shipping_days=settings.max_shipping_days,
            max_warehouse_days=settings.max_warehouse_days,
        ),
        classifier=build_classifier(),
    )


def get_pipeline(request: Request) -> AnalysisPipeline:
    """FastAPI dependency: returns the singleton pipeline from app state."""
    pipeline: AnalysisPipeline = request.app.state.pipeline
    return pipeline


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_classifier(request: Request) -> CategoryClassifier:
    """FastAPI dependency: standalone classifier for /classify."""
    pipeline: AnalysisPipeline = request.app.state.pipeline
    classifier = pipeline.classifier
    if classifier is None:
        # Should never happen — build_pipeline always sets one — but defend
        # against misconfiguration loudly rather than silently.
        raise RuntimeError("Pipeline has no classifier configured")
    return classifier


def get_tenant_config_cache(request: Request) -> TTLCache[UUID, dict[str, Any]]:
    """Returns the app-state tenant-config TTLCache.

    Lifespan-owned so test isolation works by tearing down the app and
    so a future Redis swap touches only this dependency.
    """
    cache: TTLCache[UUID, dict[str, Any]] = request.app.state.tenant_config_cache
    return cache


def get_tenant_config_service(
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    cache: Annotated[TTLCache[UUID, dict[str, Any]], Depends(get_tenant_config_cache)],
) -> TenantConfigService:
    """TenantConfigService bound to the RLS-enforced app session.

    Routes that depend on this MUST also bind the active tenant on the
    session via ``bind_tenant`` inside their own ``async with
    session.begin():`` block, otherwise RLS will silently filter
    everything out.
    """
    audit = AuditService(app_session)
    return TenantConfigService(app_session, audit, cache)


def get_ticket_service(
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> TicketService:
    """TicketService bound to the RLS-enforced app session. Same
    bind_tenant contract as TenantConfigService."""
    audit = AuditService(app_session)
    return TicketService(app_session, audit)


def get_comment_service(
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> CommentService:
    """CommentService bound to the RLS-enforced app session. Same
    bind_tenant contract as TicketService."""
    audit = AuditService(app_session)
    return CommentService(app_session, audit)


def get_review_service(
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
    cache: Annotated[TTLCache[UUID, dict[str, Any]], Depends(get_tenant_config_cache)],
) -> ReviewService:
    """ReviewService for the analyze→ticket bridge.

    Composes AuditService, TicketService, and TenantConfigService over
    a single RLS-bound app session so the route layer doesn't have to
    juggle dependencies manually. As with the other tenant-scoped
    services, the route is responsible for ``bind_tenant`` inside the
    transaction block.
    """
    audit = AuditService(app_session)
    ticket_service = TicketService(app_session, audit)
    config_service = TenantConfigService(app_session, audit, cache)
    return ReviewService(app_session, audit, ticket_service, config_service)
