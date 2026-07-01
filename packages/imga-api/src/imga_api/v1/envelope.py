"""İmga v1 response envelope + hashing + cost (contract §3/§6/§9).

§3 zarfı: {ok, request_id, response, meta:{model, processed_in, tokens{prompt,
completion,total}, latency_ms, cost_try, cached}}. model prod'da opak (prov_a),
staging'de açık ad. cost_try Gemini token'ından türetilir. context/response
SHA-256 + 200-char özet KVKK log'u için (ham gövde saklanmaz).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# TODO(finance §7): gerçek Gemini tarifesi × USD/TRY kuru. Placeholder rate;
# billing kararı VDD finance'e ait — kod hazır, rakam config'ten gelmeli.
COST_PER_1K_TOKENS_TRY = Decimal("0.50")

_RESPONSE_SUMMARY_MAX = 200


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt: int
    completion: int

    @property
    def total(self) -> int:
        return self.prompt + self.completion


def compute_cost_try(total_tokens: int) -> Decimal:
    """§6 cost_try — 4 ondalık TRY."""
    return (
        Decimal(total_tokens) / Decimal(1000) * COST_PER_1K_TOKENS_TRY
    ).quantize(Decimal("0.0001"))


def opaque_model(real_model: str, environment: str) -> str:
    """Prod'da opak kod (§3 — model adı sızmaz); staging'de açık ad."""
    return "prov_a" if environment == "production" else real_model


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def response_summary(text: str) -> str:
    return text[:_RESPONSE_SUMMARY_MAX]


def build_analyze_response(
    *,
    request_id: str,
    response_payload: dict[str, Any],
    real_model: str,
    environment: str,
    usage: TokenUsage,
    latency_ms: int,
    cost_try: Decimal,
    cached: bool = False,
    processed_in: str = "outbound",
) -> dict[str, Any]:
    """§3 tam AnalyzeResponse zarfı."""
    return {
        "ok": True,
        "request_id": request_id,
        "response": response_payload,
        "meta": {
            "model": opaque_model(real_model, environment),
            "processed_in": processed_in,  # v1.3: her zaman outbound
            "tokens": {
                "prompt": usage.prompt,
                "completion": usage.completion,
                "total": usage.total,
            },
            "latency_ms": latency_ms,
            "cost_try": float(cost_try),
            "cached": cached,
        },
    }


__all__ = [
    "COST_PER_1K_TOKENS_TRY",
    "TokenUsage",
    "compute_cost_try",
    "opaque_model",
    "sha256_hex",
    "response_summary",
    "build_analyze_response",
]
