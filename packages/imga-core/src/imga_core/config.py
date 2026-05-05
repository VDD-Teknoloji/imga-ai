"""Tunable thresholds, weights, and override scores.

All constants previously hard-coded across legacy/app.py are gathered here.
Naming reflects intent rather than legacy variable names where they were
ambiguous (e.g. legacy SHI weights are positive/neutral multipliers, not
"base/penalty").
"""

from __future__ import annotations

from typing import Final

# --- Sentiment classification thresholds (BERT score) ----------------------
SENTIMENT_NEGATIVE_THRESHOLD: Final[float] = -0.05
SENTIMENT_POSITIVE_THRESHOLD: Final[float] = 0.05

# --- Override layer scores -------------------------------------------------
KB_POSITIVE_SCORE: Final[float] = 0.9
KB_NEGATIVE_SCORE: Final[float] = -0.9
KB_NEUTRAL_SCORE: Final[float] = 0.0

CRITICAL_OVERRIDE_SCORE: Final[float] = -0.95
TIER1_OVERRIDE_SCORE: Final[float] = -0.75

SLA_COMPLIANT_SCORE: Final[float] = 0.05
SLA_BREACH_SCORE: Final[float] = -0.60

TIER2_FALLBACK_SCORE: Final[float] = -0.40
TIER2_FALLBACK_TRIGGER_THRESHOLD: Final[float] = -0.05  # only fire when score > this

# --- SLA defaults ----------------------------------------------------------
DEFAULT_MAX_SHIPPING_DAYS: Final[int] = 3
DEFAULT_MAX_WAREHOUSE_DAYS: Final[int] = 2

SLA_SHIPPING_CONTEXT_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"kargo", "sipariş", "teslim", "gelmedi", "bekliyorum"}
)
SLA_WAREHOUSE_CONTEXT_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"hazırlanıyor", "depo", "paket", "çıkış"}
)

# --- SHI (Sentiment Health Index) ------------------------------------------
SHI_POSITIVE_WEIGHT: Final[float] = 100.0
SHI_NEUTRAL_WEIGHT: Final[float] = 50.0
SHI_BASELINE: Final[float] = 50.0

# --- Crisis / executive metrics --------------------------------------------
CRISIS_SCORE_THRESHOLD: Final[float] = -0.80
HIGH_NEGATIVE_RATE: Final[float] = 0.20
TOP_BOTTLENECKS_N: Final[int] = 3

# --- BERT model ------------------------------------------------------------
DEFAULT_BERT_MODEL: Final[str] = "savasy/bert-base-turkish-sentiment-cased"
# Sprint 9.0 — bumped 32 -> 128. Single biggest immediate win for the
# 10K-row batch demo path: the HF pipeline groups ~4x more texts into
# one forward pass, slashing per-row Python/tokenizer overhead. Memory
# headroom on the api container (3 GiB limit) absorbs the wider tensor
# without spilling. If a downstream model with smaller context shows
# OOMs, drop the per-instance kwarg in `BertSentimentAnalyzer(...)`.
DEFAULT_BERT_BATCH_SIZE: Final[int] = 128
BERT_MAX_LENGTH: Final[int] = 512

# --- Knowledge base CSV schema --------------------------------------------
KB_TEXT_COLUMNS: Final[tuple[str, ...]] = (
    "Müşteri Yorumu",
    "Review",
    "review",
    "comments",
    "Yorum",
)
KB_LABEL_COLUMN: Final[str] = "Correct Label"

# --- Label mapping ---------------------------------------------------------
LABEL_NEGATIVE: Final[str] = "NEGATIF"
LABEL_NEUTRAL: Final[str] = "NÖTR"
LABEL_POSITIVE: Final[str] = "POZITIF"

# Map legacy / KB titlecase labels to canonical uppercase form.
LEGACY_LABEL_MAP: Final[dict[str, str]] = {
    "Pozitif": LABEL_POSITIVE,
    "Nötr": LABEL_NEUTRAL,
    "Negatif": LABEL_NEGATIVE,
    "POZITIF": LABEL_POSITIVE,
    "NÖTR": LABEL_NEUTRAL,
    "NEGATIF": LABEL_NEGATIVE,
    "positive": LABEL_POSITIVE,
    "neutral": LABEL_NEUTRAL,
    "negative": LABEL_NEGATIVE,
}

# --- Category classification (Sprint 6) -----------------------------------
# Confidence below which the keyword classifier flags requires_manual_review.
CATEGORY_KEYWORD_MIN_CONFIDENCE: Final[float] = 0.3

# Threshold above which keyword confidence is "good enough" to skip the LLM.
# Low confidence (between MIN and FALLBACK) routes to LLM if available.
CATEGORY_LLM_FALLBACK_THRESHOLD: Final[float] = 0.7

# Hit count is normalised by dividing by this. Cap at 1.0.
# 5 hits => confidence 1.0; 1 hit => 0.2; 2 hits => 0.4.
CATEGORY_NORMALIZATION_DIVISOR: Final[float] = 5.0

# How many secondary categories to include in the result.
CATEGORY_SECONDARY_COUNT: Final[int] = 2

# Code returned when no category matches. Mirrors taxonomy.FALLBACK_CATEGORY_CODE.
CATEGORY_FALLBACK_CODE: Final[str] = "belirsiz"
