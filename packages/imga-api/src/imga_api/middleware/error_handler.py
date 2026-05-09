"""Sprint 9.1 C — generic 5xx handler.

FastAPI surfaces unhandled exceptions as a bare 500 response body
(``Internal Server Error``) and logs the traceback through uvicorn's
default logger. Both layers strip the request id, so a support
ticket that says "I got a 500 around 14:32" is hard to correlate
with a specific log line.

This handler:

  * logs ``logger.exception(...)`` with structured ``extra`` so the
    JSON-output handler attaches request_id / tenant_id / user_id /
    method / path on the same record;
  * returns a JSON body containing ``error`` + ``request_id`` so the
    client can show the id to the user (or include it in a sentry-
    style report).

HTTPException stays untouched — FastAPI's built-in handler already
honours ``detail`` and the rate limiter / auth deps depend on that
behaviour. Only "I really wasn't expecting this" exceptions land
here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import status
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


_logger = logging.getLogger("imga-api")


def register_error_handlers(app: FastAPI) -> None:
    """Wire the generic 5xx handler onto ``app``. Idempotent."""

    @app.exception_handler(Exception)
    async def _generic_500(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001 — FastAPI signature
        request_id = getattr(request.state, "request_id", None)
        # Tenant + user only available after auth middleware has run.
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = getattr(request.state, "user_id", None)
        _logger.exception(
            "unhandled error in %s %s",
            request.method,
            request.url.path,
            extra={
                "request_id": request_id,
                "tenant_id": str(tenant_id) if tenant_id else None,
                "user_id": str(user_id) if user_id else None,
                "method": request.method,
                "path": request.url.path,
                "exception_type": type(exc).__name__,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id} if request_id else None,
        )
