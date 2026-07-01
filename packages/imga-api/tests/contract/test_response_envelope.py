"""Contract §3 — AnalyzeResponse zarf şekli + §4 response şemaları (birim)."""

from __future__ import annotations

from decimal import Decimal

from imga_api.v1.envelope import (
    TokenUsage,
    build_analyze_response,
    compute_cost_try,
    opaque_model,
)
from imga_api.v1.prompts import PROMPTS

# Contract §4 response shape'lerinin zorunlu alanları.
_EXPECTED_REQUIRED = {
    "anomaly-explain": {"analysis", "root_causes", "actions"},
    "ticket-analyze": {"sentiment", "category", "urgency", "tags", "language_detected"},
    "ticket-suggest-reply": {"reply_draft", "sources_used", "warnings"},
    "return-analyze": {"patterns", "causes", "recommendations"},
    "cargo-optimize": {"suggestion", "delay_forecast"},
    "free-analyze": {"answer_markdown", "follow_up_prompts"},
}


def test_response_envelope_shape() -> None:
    env = build_analyze_response(
        request_id="rid",
        response_payload={"a": 1},
        real_model="gemini-2.5-pro",
        environment="staging",
        usage=TokenUsage(prompt=10, completion=5),
        latency_ms=123,
        cost_try=Decimal("0.0075"),
    )
    assert env["ok"] is True
    assert env["request_id"] == "rid"
    assert env["response"] == {"a": 1}
    meta = env["meta"]
    assert set(meta) == {
        "model",
        "processed_in",
        "tokens",
        "latency_ms",
        "cost_try",
        "cached",
    }
    assert meta["processed_in"] == "outbound"
    assert set(meta["tokens"]) == {"prompt", "completion", "total"}
    assert meta["tokens"]["total"] == 15
    assert meta["cached"] is False


def test_opaque_model_prod_vs_staging() -> None:
    assert opaque_model("gemini-2.5-pro", "production") == "prov_a"
    assert opaque_model("gemini-2.5-pro", "staging") == "gemini-2.5-pro"


def test_cost_try_4_decimal() -> None:
    c = compute_cost_try(899)
    assert str(c) == "0.4495"


def test_use_case_schemas_cover_contract() -> None:
    assert set(PROMPTS) == set(_EXPECTED_REQUIRED)
    for uc, expected in _EXPECTED_REQUIRED.items():
        schema = PROMPTS[uc].response_schema
        assert schema["type"] == "object"
        assert set(schema["required"]) == expected
        # her required alan properties'te tanımlı
        for field in expected:
            assert field in schema["properties"]
