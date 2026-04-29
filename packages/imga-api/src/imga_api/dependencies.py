"""FastAPI dependency providers — singleton pipeline kept on app.state."""

from __future__ import annotations

from fastapi import Request
from imga_core import (
    AnalysisPipeline,
    BertSentimentAnalyzer,
    CategoryClassifier,
    HybridClassifier,
    KeywordCategoryClassifier,
    SLAParams,
    create_llm_provider,
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


def build_pipeline(settings: Settings) -> AnalysisPipeline:
    """Construct the pipeline. Called once at startup."""
    return AnalysisPipeline(
        analyzer=BertSentimentAnalyzer(model_name=settings.bert_model),
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
