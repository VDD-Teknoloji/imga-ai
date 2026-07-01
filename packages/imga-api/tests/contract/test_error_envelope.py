"""Contract §3/§5 — AnalyzeError zarf şekli (birim; app gerektirmez)."""

from __future__ import annotations

import pytest

from imga_api.v1.errors import ERROR_CODES, PartnerApiError, error_body


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
