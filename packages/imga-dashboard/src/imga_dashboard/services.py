"""Cached pipeline + dataframe processing helpers."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st
from imga_core import (
    AnalysisPipeline,
    AnalysisResult,
    BertSentimentAnalyzer,
    HybridClassifier,
    KeywordCategoryClassifier,
    SLAParams,
    create_llm_provider,
)
from imga_core.categories import GLOBAL_CATEGORY_BY_CODE

from imga_dashboard.paths import params_path, rules_path, training_data_path

POSSIBLE_TEXT_COLUMNS = ("Müşteri Yorumu", "Review", "review", "comments", "Yorum")


def _build_classifier() -> KeywordCategoryClassifier | HybridClassifier:
    keyword = KeywordCategoryClassifier()
    llm = create_llm_provider()
    if llm is None:
        return keyword
    return HybridClassifier(keyword_classifier=keyword, llm_provider=llm)


@st.cache_resource(show_spinner="Loading BERT model...")
def _load_pipeline(
    sla_shipping: int, sla_warehouse: int
) -> AnalysisPipeline:
    return AnalysisPipeline(
        analyzer=BertSentimentAnalyzer(),
        knowledge_base_path=training_data_path() if training_data_path().exists() else None,
        rules_path=rules_path() if rules_path().exists() else None,
        sla_params=SLAParams(max_shipping_days=sla_shipping, max_warehouse_days=sla_warehouse),
        classifier=_build_classifier(),
    )


def get_pipeline() -> AnalysisPipeline:
    p = load_params()
    return _load_pipeline(
        sla_shipping=int(p.get("max_shipping_days", 3)),
        sla_warehouse=int(p.get("max_warehouse_days", 2)),
    )


def detect_text_column(df: pd.DataFrame) -> str | None:
    for col in POSSIBLE_TEXT_COLUMNS:
        if col in df.columns:
            return col
    return None


def load_dataframe(uploaded_file: Any) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file)
    return pd.read_csv(uploaded_file)


def analyze_dataframe(df: pd.DataFrame, text_col: str) -> list[AnalysisResult]:
    pipeline = get_pipeline()
    texts: list[str] = [str(t) if pd.notna(t) else "" for t in df[text_col]]
    return pipeline.analyze_batch(texts)


def results_to_dataframe(
    df: pd.DataFrame, text_col: str, results: list[AnalysisResult]
) -> pd.DataFrame:
    enriched = df.copy()
    enriched[text_col] = [r.text for r in results]
    enriched["Sentiment"] = [r.sentiment_label for r in results]
    enriched["Score"] = [r.sentiment_score for r in results]
    enriched["Risk"] = [_risk_emoji(r.sentiment_label) for r in results]
    enriched["Birim"] = [_category_label(r) for r in results]
    enriched["Güven"] = [_category_confidence(r) for r in results]
    enriched["Diğer İlgili Birimler"] = [_secondary_labels(r) for r in results]
    enriched["Customer Perspective"] = [r.customer_perspective for r in results]
    enriched["Company Perspective"] = [r.company_perspective for r in results]
    enriched["Summary"] = [r.summary or "" for r in results]
    enriched["SLA"] = [r.sla_detected or "" for r in results]
    enriched = enriched.sort_values(by="Score", ascending=True)
    return enriched


def _category_label(result: AnalysisResult) -> str:
    cat = result.categorization
    if cat is None:
        return ""
    definition = GLOBAL_CATEGORY_BY_CODE.get(cat.primary)
    name = definition.name if definition else cat.primary
    if cat.requires_manual_review:
        return f"⚠️ {name}"
    return name


def _category_confidence(result: AnalysisResult) -> str:
    cat = result.categorization
    if cat is None:
        return ""
    return f"{cat.primary_confidence * 100:.0f}%"


def _secondary_labels(result: AnalysisResult) -> str:
    cat = result.categorization
    if cat is None or not cat.secondaries:
        return ""
    parts: list[str] = []
    for hit in cat.secondaries:
        definition = GLOBAL_CATEGORY_BY_CODE.get(hit.category)
        name = definition.name if definition else hit.category
        parts.append(f"{name} ({hit.confidence * 100:.0f}%)")
    return ", ".join(parts)


def category_distribution(results: list[AnalysisResult]) -> pd.DataFrame:
    """Per-category counts with display names, sorted descending."""
    counts: dict[str, int] = {}
    for r in results:
        if r.categorization is None:
            continue
        counts[r.categorization.primary] = counts.get(r.categorization.primary, 0) + 1
    rows: list[dict[str, str | int]] = []
    for code, count in counts.items():
        definition = GLOBAL_CATEGORY_BY_CODE.get(code)
        name = definition.name if definition else code
        rows.append({"Birim": name, "Şikayet Sayısı": count})
    if not rows:
        return pd.DataFrame(columns=["Birim", "Şikayet Sayısı"])
    return pd.DataFrame(rows).sort_values(by="Şikayet Sayısı", ascending=False)


def _risk_emoji(label: str) -> str:
    return {"NEGATIF": "🔴 Negatif", "POZITIF": "🟢 Pozitif", "NÖTR": "⚪ Nötr"}.get(label, label)


# --- JSON state persistence (rules + SLA params) -------------------------


def load_rules() -> dict[str, list[dict[str, Any]]]:
    p = rules_path()
    if not p.exists():
        return {"customer_rules": [], "company_rules": []}
    try:
        data: dict[str, list[dict[str, Any]]] = json.loads(p.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return {"customer_rules": [], "company_rules": []}


def save_rules(rules: dict[str, list[dict[str, Any]]]) -> None:
    rules_path().write_text(
        json.dumps(rules, ensure_ascii=False, indent=4), encoding="utf-8"
    )


def load_params() -> dict[str, int]:
    p = params_path()
    defaults = {"max_shipping_days": 3, "max_warehouse_days": 2}
    if not p.exists():
        return defaults
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {**defaults, **data}
    except (OSError, json.JSONDecodeError):
        return defaults


def save_params(params: dict[str, int]) -> None:
    params_path().write_text(
        json.dumps(params, ensure_ascii=False, indent=4), encoding="utf-8"
    )


def append_corrections(corrections: pd.DataFrame, text_col: str) -> None:
    """Append user corrections to training_data.csv for the knowledge base."""
    p = training_data_path()
    file_exists = p.exists() and p.stat().st_size > 0
    payload = corrections[[text_col, "Best Label", "Reason"]].rename(
        columns={"Best Label": "Correct Label"}
    )
    payload["Timestamp"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    payload.to_csv(p, mode="a", index=False, header=not file_exists, encoding="utf-8")


def reset_pipeline_cache() -> None:
    """Drop the cached pipeline so a fresh KB / rules state is loaded."""
    _load_pipeline.clear()  # type: ignore[attr-defined]
