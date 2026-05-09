"""Sprint 9.1 C — per-request id propagation.

Every request gets an ``X-Request-ID`` (preferred from the inbound
header, freshly minted otherwise). The id is exposed in three places
so a single value threads through every layer that might surface it:

  * ``request.state.request_id`` — handlers / dependencies read it.
  * ``request_id_var`` (ContextVar) — log records pick it up via the
    ``RequestIDLogFilter`` so structured-log handlers don't need to
    accept ``extra={"request_id": ...}`` at every call site.
  * Response header ``X-Request-ID`` — the browser / curl / support
    ticket has the same id the log entries do.

The middleware deliberately does not validate the inbound header
beyond a length cap and an alphanumeric/hyphen filter — that's enough
to stop log injection without forcing clients onto a strict UUID.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


# Permits 8 .. 64 chars of [A-Za-z0-9_-] — covers UUIDs, hex, ULIDs,
# slugs. Anything else gets replaced rather than echoed.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# ContextVar so log filters can pull the current request id without
# forcing every log call to pass ``extra={"request_id": ...}``.
request_id_var: ContextVar[str | None] = ContextVar(
    "request_id", default=None
)


class RequestIDLogFilter(logging.Filter):
    """Inject the active request_id onto every LogRecord. Records that
    arrive outside any request context get an empty string so format
    strings using ``%(request_id)s`` don't blow up."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or ""
        return True


def _normalise_request_id(raw: str | None) -> str:
    if raw is None:
        return uuid.uuid4().hex
    raw = raw.strip()
    if _VALID_REQUEST_ID.match(raw):
        return raw
    # Unsafe inbound — mint our own, don't trust user input as a log
    # token.
    return uuid.uuid4().hex


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Starlette middleware: read X-Request-ID, fall back to a fresh
    uuid4-hex, expose on ``request.state`` + ContextVar + response."""

    HEADER_NAME = "X-Request-ID"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = _normalise_request_id(request.headers.get(self.HEADER_NAME))
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[self.HEADER_NAME] = rid
        return response
