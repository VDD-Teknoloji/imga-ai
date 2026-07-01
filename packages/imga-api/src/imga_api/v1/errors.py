"""İmga v1 partner API hata zarfı (contract §3/§5).

Tüm /v1 hataları ``AnalyzeError`` shape'inde döner:
``{ok: false, request_id, error: {code, message, details?, retry_after_seconds?}}``.
``PartnerApiError`` fırlatılır; main.py'deki handler bunu bu zarfa render eder
(request_id + X-Imga-Request-Id header ile).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Contract §5 tam kod listesi.
ERROR_CODES = frozenset(
    {
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
)


@dataclass
class PartnerApiError(Exception):
    """/v1 hata — main.py handler AnalyzeError'a çevirir."""

    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None
    retry_after_seconds: int | None = None
    # §6: 429'da rate-limit/quota header'ları yanıtta olmalı — handler uygular.
    extra_headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        # Kontrat dışı bir kod erken yakalansın (yazım hatası = test-time bug).
        if self.code not in ERROR_CODES:
            raise ValueError(f"unknown error code: {self.code!r}")


def error_body(request_id: str, err: PartnerApiError) -> dict[str, Any]:
    """PartnerApiError → AnalyzeError gövdesi (§3)."""
    inner: dict[str, Any] = {"code": err.code, "message": err.message}
    if err.details is not None:
        inner["details"] = err.details
    if err.retry_after_seconds is not None:
        inner["retry_after_seconds"] = err.retry_after_seconds
    return {"ok": False, "request_id": request_id, "error": inner}


async def partner_api_exception_handler(
    request: Request, exc: PartnerApiError
) -> JSONResponse:
    """main.py'de register edilir. AnalyzeError gövdesi + X-Imga-Request-Id
    header (RequestIDMiddleware'in request.state.request_id'sini kullanır)."""
    rid = getattr(request.state, "request_id", "") or ""
    resp = JSONResponse(
        status_code=exc.status_code, content=error_body(rid, exc)
    )
    resp.headers["X-Imga-Request-Id"] = rid
    if exc.retry_after_seconds is not None:
        resp.headers["Retry-After"] = str(exc.retry_after_seconds)
    if exc.extra_headers:
        for k, v in exc.extra_headers.items():
            resp.headers[k] = v
    return resp


async def v1_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 422 → AnalyzeError(400, invalid_input) — YALNIZ /v1 için.

    Kontrat değişmezi: tüm /v1 hataları AnalyzeError zarfında. FastAPI'nin
    varsayılan 422 gövdesi (``{detail:[...]}``) bunu ihlal eder. /v1 dışı
    yollar varsayılan handler'a devredilir (mevcut API'yi bozmamak için).

    KVKK: pydantic hata girişi ``input`` ham gövde parçası içerebilir →
    yankılanMAZ. Yalnız ``loc``/``msg``/``type`` sızdırılır.
    """
    if not request.url.path.startswith("/v1/"):
        return await request_validation_exception_handler(request, exc)
    rid = getattr(request.state, "request_id", "") or ""
    safe_errors = [
        {
            "loc": [str(p) for p in err.get("loc", ())],
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    err = PartnerApiError(
        status_code=400,
        code="invalid_input",
        message="request validation failed",
        details={"errors": safe_errors},
    )
    resp = JSONResponse(status_code=400, content=error_body(rid, err))
    resp.headers["X-Imga-Request-Id"] = rid
    return resp


__all__ = [
    "ERROR_CODES",
    "PartnerApiError",
    "error_body",
    "partner_api_exception_handler",
    "v1_validation_exception_handler",
]
