"""FastAPI dependency providers — singleton pipeline kept on app.state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request
from imga_core import AnalysisPipeline, BertSentimentAnalyzer, SLAParams

from imga_api.settings import Settings

if TYPE_CHECKING:
    pass


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
    )


def get_pipeline(request: Request) -> AnalysisPipeline:
    """FastAPI dependency: returns the singleton pipeline from app state."""
    pipeline: AnalysisPipeline = request.app.state.pipeline
    return pipeline


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings
