"""İmga v1 — use-case system prompt + Gemini response schema (contract §4).

Her use_case için (system_prompt, response_schema, temperature). response_schema
Gemini structured-output (response_mime_type=application/json) içindir ve
contract §4 response shape'ine birebir uyar. Prompt'lar versiyonlu (v1); değişim
= yeni sürüm. Türkçe e-ticaret bağlamı; çıktı YALNIZ JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class UseCasePrompt:
    system_prompt: str
    response_schema: dict[str, Any]
    temperature: float = 0.2
    max_output_tokens: int = 4096


_ONLY_JSON = "Yalnızca geçerli JSON döndür; açıklama/markdown ekleme."

_ANOMALY = UseCasePrompt(
    system_prompt=(
        "Sen bir e-ticaret KPI analistisin. Verilen KPI anlık görüntüsü ve "
        "önceki döneme göre değişimlerden yola çıkarak kısa bir açıklama, kök "
        "nedenler ve öncelikli aksiyonlar üret. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["analysis", "root_causes", "actions"],
        "properties": {
            "analysis": {"type": "string"},
            "root_causes": {"type": "array", "items": {"type": "string"}},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["title", "priority", "owner_role"],
                    "properties": {
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["high", "med", "low"]},
                        "owner_role": {"type": "string"},
                    },
                },
            },
        },
    },
)

_TICKET_ANALYZE = UseCasePrompt(
    system_prompt=(
        "Sen bir müşteri destek analistisin. Verilen destek talebini analiz et: "
        "duygu, kategori, aciliyet (1-5), etiketler ve algılanan dil. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["sentiment", "category", "urgency", "tags", "language_detected"],
        "properties": {
            "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "category": {"type": "string"},
            "urgency": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "language_detected": {"type": "string"},
        },
    },
)

_SUGGEST_REPLY = UseCasePrompt(
    system_prompt=(
        "Sen bir müşteri destek temsilcisisin. Verilen talep, müşteri profili, "
        "politika parçaları ve tona göre nazik bir yanıt taslağı üret. "
        "reply_draft istenen tonda, sources_used kullanılan politikalar, warnings "
        "dikkat notları. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["reply_draft", "sources_used", "warnings"],
        "properties": {
            "reply_draft": {"type": "string"},
            "sources_used": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    },
    temperature=0.4,
)

_RETURN = UseCasePrompt(
    system_prompt=(
        "Sen bir iade analistisin. Verilen iade listesinden örüntüleri (label + "
        "yüzde), kök neden hipotezlerini (kanıtla) ve önerileri çıkar. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["patterns", "causes", "recommendations"],
        "properties": {
            "patterns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "share_pct"],
                    "properties": {
                        "label": {"type": "string"},
                        "share_pct": {"type": "number"},
                    },
                },
            },
            "causes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["hypothesis", "evidence"],
                    "properties": {
                        "hypothesis": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                },
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
    },
)

_CARGO = UseCasePrompt(
    system_prompt=(
        "Sen bir kargo/lojistik optimizasyon uzmanısın. Sipariş + kargo geçmişine "
        "göre en iyi kargo şirketini (gerekçe + tahmini TRY maliyet) ve gecikme "
        "öngörüsünü (p50/p90 gün + risk bayrakları) üret. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["suggestion", "delay_forecast"],
        "properties": {
            "suggestion": {
                "type": "object",
                "required": ["carrier", "reason", "est_cost_try"],
                "properties": {
                    "carrier": {"type": "string"},
                    "reason": {"type": "string"},
                    "est_cost_try": {"type": "number"},
                },
            },
            "delay_forecast": {
                "type": "object",
                "required": ["p50_days", "p90_days", "risk_flags"],
                "properties": {
                    "p50_days": {"type": "number"},
                    "p90_days": {"type": "number"},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
)

_FREE = UseCasePrompt(
    system_prompt=(
        "Sen bir e-ticaret veri analiz asistanısın. Kullanıcının sorusunu verilen "
        "anlık görüntü bağlamında Türkçe, markdown yanıtla (answer_markdown), "
        "gerekiyorsa grafik öner (charts_suggested) ve takip soruları üret. " + _ONLY_JSON
    ),
    response_schema={
        "type": "object",
        "required": ["answer_markdown", "follow_up_prompts"],
        "properties": {
            "answer_markdown": {"type": "string"},
            "charts_suggested": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind", "series"],
                    "properties": {
                        "kind": {"type": "string", "enum": ["line", "bar", "pie"]},
                        "series": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "follow_up_prompts": {"type": "array", "items": {"type": "string"}},
        },
    },
    temperature=0.5,
)

PROMPTS: dict[str, UseCasePrompt] = {
    "anomaly-explain": _ANOMALY,
    "ticket-analyze": _TICKET_ANALYZE,
    "ticket-suggest-reply": _SUGGEST_REPLY,
    "return-analyze": _RETURN,
    "cargo-optimize": _CARGO,
    "free-analyze": _FREE,
}

__all__ = ["UseCasePrompt", "PROMPTS"]
