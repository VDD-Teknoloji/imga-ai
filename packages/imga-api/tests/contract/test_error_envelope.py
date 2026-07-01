"""Contract §3/§5 — AnalyzeError zarf şekli (birim; app gerektirmez)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.exceptions import RequestValidationError

from imga_api.v1.errors import (
    ERROR_CODES,
    PartnerApiError,
    error_body,
    v1_validation_exception_handler,
)


def test_all_codes_valid() -> None:
    # §5 tam liste
    assert ERROR_CODES == {
        "invalid_input",
        "export_window_too_large",
        "auth_failed",
        "residency_denied",
        "session_not_found",
        "rate_limit",
        "quota_exceeded",
        "provider_error",
        "timeout",
    }


@pytest.mark.parametrize("code", sorted(ERROR_CODES))
def test_error_body_shape(code: str) -> None:
    err = PartnerApiError(status_code=400, code=code, message="m")
    body = error_body("req-1", err)
    assert body["ok"] is False
    assert body["request_id"] == "req-1"
    assert body["error"]["code"] == code
    assert body["error"]["message"] == "m"
    # opsiyonel alanlar yoksa gövdede olmamalı
    assert "details" not in body["error"]
    assert "retry_after_seconds" not in body["error"]


def test_error_body_optional_fields() -> None:
    err = PartnerApiError(
        status_code=429,
        code="rate_limit",
        message="m",
        details={"hint": "x"},
        retry_after_seconds=30,
    )
    body = error_body("r", err)
    assert body["error"]["details"] == {"hint": "x"}
    assert body["error"]["retry_after_seconds"] == 30


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValueError):
        PartnerApiError(status_code=400, code="not_a_code", message="m")


def test_v1_validation_maps_to_analyze_error_no_body_leak() -> None:
    # Pydantic 422 → AnalyzeError(400, invalid_input); ham input SIZMAZ (KVKK).
    exc = RequestValidationError(
        [
            {
                "loc": ("body", "user_prompt"),
                "msg": "Field required",
                "type": "missing",
                "input": {"SECRET_BODY": "leak-me"},
            }
        ]
    )
    req = SimpleNamespace(
        url=SimpleNamespace(path="/v1/analyze/free-analyze"),
        state=SimpleNamespace(request_id="rid-9"),
    )
    resp = asyncio.run(v1_validation_exception_handler(req, exc))
    body = json.loads(resp.body)
    assert resp.status_code == 400
    assert body["ok"] is False and body["request_id"] == "rid-9"
    assert body["error"]["code"] == "invalid_input"
    first = body["error"]["details"]["errors"][0]
    assert first["loc"] == ["body", "user_prompt"] and first["type"] == "missing"
    raw = json.dumps(body)
    assert "SECRET_BODY" not in raw and "leak-me" not in raw
    assert resp.headers["X-Imga-Request-Id"] == "rid-9"
