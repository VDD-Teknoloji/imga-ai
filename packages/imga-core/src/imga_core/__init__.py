"""imga-core: headless sentiment analysis pipeline for Turkish customer reviews."""

from imga_core.analyzers import AnalyzerPrediction, BertSentimentAnalyzer, SentimentAnalyzer
from imga_core.classifiers import CategoryClassifier, KeywordCategoryClassifier
from imga_core.llm import LLMProvider, LLMProviderError, create_llm_provider
from imga_core.metrics import (
    ExecutiveMetrics,
    calculate_executive_metrics,
    calculate_shi,
    count_crises,
    is_alert_state,
    negative_rate,
    top_bottlenecks,
)
from imga_core.models import (
    AnalysisRequest,
    AnalysisResult,
    CategoryClassification,
    CategoryHit,
    ClassificationMethod,
    LLMClassificationResult,
    OverrideHit,
    OverrideLayer,
    RiskClass,
    SentimentLabel,
)
from imga_core.overrides import KnowledgeBase, SLAParams
from imga_core.pipeline import AnalysisPipeline
from imga_core.rules import Rule, RuleEngine, RuleSet

__version__ = "0.1.0"

__all__ = [
    "AnalysisPipeline",
    "AnalysisRequest",
    "AnalysisResult",
    "AnalyzerPrediction",
    "BertSentimentAnalyzer",
    "CategoryClassification",
    "CategoryClassifier",
    "CategoryHit",
    "ClassificationMethod",
    "ExecutiveMetrics",
    "KeywordCategoryClassifier",
    "KnowledgeBase",
    "LLMClassificationResult",
    "LLMProvider",
    "LLMProviderError",
    "OverrideHit",
    "OverrideLayer",
    "RiskClass",
    "Rule",
    "RuleEngine",
    "RuleSet",
    "SLAParams",
    "SentimentAnalyzer",
    "SentimentLabel",
    "__version__",
    "calculate_executive_metrics",
    "calculate_shi",
    "count_crises",
    "create_llm_provider",
    "is_alert_state",
    "negative_rate",
    "top_bottlenecks",
]
