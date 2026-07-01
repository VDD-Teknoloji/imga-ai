"""İmga v1 — free-analyze SSE (contract §7). İki-adım handshake.

1. POST /v1/analyze/free-analyze/stream-token (tenant Bearer) → {stream_token,
   expires_in:60}. İsteği Redis'te 60s tek-kullanımlık saklar (bearer query'de gitmez).
2. GET /v1/analyze/stream?token=<> → text/event-stream: partial / meta / done,
   15s heartbeat. meta.processed_in NORMATİF (§7 v1.2).

Gerçek Gemini token-stream (``generate_content_stream``): partial event'leri
model ürettikçe akar (ilk-token TTFT'ye bağlı). SSE olay şekli contract §7 ile
birebir. Redis down → 503-benzeri (stream başlatılamaz).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from imga_api.cache.redis_client import get_redis_client
from imga_api.v1.auth import ApiPrincipal, require_tenant
from imga_api.v1.envelope import TokenUsage, compute_cost_try
from imga_api.v1.errors import PartnerApiError
from imga_api.services.partner_analyze import stream_free_analyze

router = APIRouter(prefix="/v1/analyze", tags=["v1-analyze"])

_STREAM_TTL = 60


class StreamRequest(BaseModel):
    tenant_id: str
    use_case: str
    period: str = "custom"
    period_start: str = ""
    period_end: str = ""
    context: dict = {}
    user_prompt: str | None = None
    language: str = "tr"
    session_id: UUID | None = None
    client_request_id: UUID


class StreamTokenResponse(BaseModel):
    stream_token: str
    expires_in: int


@router.post("/free-analyze/stream-token", response_model=StreamTokenResponse)
async def stream_token(
    body: StreamRequest,
    principal: Annotated[ApiPrincipal, Depends(require_tenant)],
) -> StreamTokenResponse:
    if body.use_case != "free-analyze":
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_input",
            message="stream-token only for free-analyze",
            details={"field": "use_case"},
        )
    if not (body.user_prompt or "").strip():
        raise PartnerApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_input",
            message="user_prompt required for free-analyze",
            details={"field": "user_prompt", "reason": "required_for_free_analyze"},
        )
    gemini_prompt = json.dumps(
        {
            "language": body.language,
            "context": body.context,
            "user_prompt": body.user_prompt,
        },
        ensure_ascii=False,
    )
    token = "st_" + secrets.token_urlsafe(24)
    payload = json.dumps(
        {"tenant_id": str(principal.tenant_id), "gemini_prompt": gemini_prompt}
    )
    try:
        client = get_redis_client()
        await client.set(f"imgav1:stream:{token}", payload, ex=_STREAM_TTL, nx=True)
    except Exception as exc:  # noqa: BLE001
        raise PartnerApiError(
            status_code=502,
            code="provider_error",
            message="stream store unavailable",
        ) from exc
    return StreamTokenResponse(stream_token=token, expires_in=_STREAM_TTL)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_stream(
    deltas: AsyncIterator[tuple[str, TokenUsage | None]],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[str]:
    """``(delta, usage)`` akışını contract §7 SSE event'lerine çevir:
    ``partial`` (her delta) → ``meta`` (tokens+cost_try+processed_in) → ``done``.
    PartnerApiError → ``error`` event. Client disconnect → erken dur (o ana kadarki
    token'lar meta'ya girmez; stream kapanır). Saf/test edilebilir: engine mock'lanır."""
    yield ": ping\n\n"  # bağlantı ack (ilk-byte)
    last_usage: TokenUsage | None = None
    total_len = 0
    try:
        async for delta, usage in deltas:
            if await is_disconnected():
                return
            if usage is not None:
                last_usage = usage
            if delta:
                total_len += len(delta)
                yield _sse("partial", {"delta": delta})
    except PartnerApiError as exc:
        yield _sse("error", {"code": exc.code, "message": exc.message})
        return
    u = last_usage or TokenUsage(prompt=0, completion=0)
    cost = compute_cost_try(u.total)
    yield _sse(
        "meta",
        {
            "tokens": {"prompt": u.prompt, "completion": u.completion},
            "cost_try": float(cost),
            "processed_in": "outbound",  # §7 normatif
        },
    )
    yield _sse("done", {"finish_reason": "stop", "final_length": total_len})


@router.get("/stream")
async def stream(
    request: Request,
    token: Annotated[str, Query()],
) -> StreamingResponse:
    # Auth = tek-kullanımlık stream_token (GET&DELETE).
    key = f"imgav1:stream:{token}"
    try:
        client = get_redis_client()
        raw = await client.get(key)
        if raw is not None:
            await client.delete(key)  # tek kullanımlık
    except Exception:  # noqa: BLE001
        raw = None
    if not raw:
        raise PartnerApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="session_not_found",
            message="stream token invalid/expired/used",
        )
    stored = json.loads(raw)
    gemini_prompt = stored["gemini_prompt"]

    return StreamingResponse(
        sse_stream(
            stream_free_analyze(gemini_prompt),
            is_disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
    )
