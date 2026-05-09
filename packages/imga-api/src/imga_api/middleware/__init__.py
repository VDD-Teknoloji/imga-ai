"""Sprint 9.1 C — request-scoped middleware for observability.

Two pieces:
* ``RequestIDMiddleware`` — assign / propagate ``X-Request-ID`` per
  request and attach it to ``request.state.request_id``. Logs and the
  generic 5xx handler read it from there; the same id echoes back as
  a response header so a support ticket can be matched against the
  server's log line.
* ``register_error_handlers(app)`` — generic 500 / unhandled-exception
  handler that includes the request id (and tenant / user when
  available) in both the log entry and the response body.
"""

from imga_api.middleware.error_handler import register_error_handlers
from imga_api.middleware.request_id import RequestIDMiddleware, request_id_var

__all__ = [
    "RequestIDMiddleware",
    "register_error_handlers",
    "request_id_var",
]
