"""Auth endpoints — login, refresh w/ chain detection, logout, /me, switch-tenant, change-password."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from imga_db.models import Tenant, User
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import (
    CurrentUser,
    get_auth_service,
    get_current_user,
    get_settings,
)
from imga_api.db_deps import get_admin_session
from imga_api.rate_limit import check_rate_limit, rate_limit_ip
from imga_api.services import AuthError, AuthService, TokenReuseDetectedError
from imga_api.settings import Settings

router = APIRouter(prefix="/auth", tags=["Auth"])


# --- request / response models ------------------------------------------


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "alice@acme.com",
                "password": "Alice-Secure-Pwd-123!",
                "active_tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        },
    )
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)
    # Optional: choose tenant at login time. If omitted, the first
    # available tenant is selected (or None for super-admin with no link).
    active_tenant_id: UUID | None = None


class RefreshRequest(BaseModel):
    """Sprint 9.0.6 B — refresh_token is optional in the body. When the
    HttpOnly cookie path is used the token rides on the request as a
    cookie and the body is empty ``{}``. Bearer-style integrations can
    keep posting the token explicitly."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6..."}
        },
    )
    refresh_token: str | None = Field(default=None, min_length=1)


class LogoutRequest(BaseModel):
    """Same dual-source convention as RefreshRequest."""

    model_config = ConfigDict(extra="forbid")
    refresh_token: str | None = Field(default=None, min_length=1)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "current_password": "Alice-Secure-Pwd-123!",
                "new_password": "Alice-Even-Better-Pwd-456!",
            }
        },
    )
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=256)


class SwitchTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


class TenantSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str
    language: str = "tr"


class UserSummary(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_super_admin: bool


class ActiveContext(BaseModel):
    tenant_id: UUID | None
    tenant_name: str | None
    tenant_slug: str | None
    role: str | None
    # Aktif kurumun arayüz + AI çıktı dili — frontend locale'i bununla ayarlar.
    language: str = "tr"


class MeResponse(BaseModel):
    user: UserSummary
    active_context: ActiveContext
    available_tenants: list[TenantSummary]


# --- cookie helpers -----------------------------------------------------


def _set_auth_cookies(
    response: Response,
    settings: Settings,
    *,
    access_token: str,
    refresh_token: str,
) -> None:
    """Sprint 9.0.6 B — write HttpOnly cookies alongside the JSON body.

    The JSON body still carries the tokens for callers that prefer the
    explicit Bearer flow (CLI, integrations, server-to-server). Browser
    clients pivot to ``credentials: "include"`` and read no token from
    the response; the server enforces auth via the cookie on subsequent
    requests."""
    cookies = settings.cookies
    samesite_typed: Any = cookies.samesite  # narrow at call site
    response.set_cookie(
        key=cookies.access_name,
        value=access_token,
        max_age=settings.jwt.access_token_ttl_minutes * 60,
        httponly=True,
        secure=cookies.secure,
        samesite=samesite_typed,
        domain=cookies.domain,
        path=cookies.path,
    )
    response.set_cookie(
        key=cookies.refresh_name,
        value=refresh_token,
        max_age=settings.jwt.refresh_token_ttl_days * 24 * 60 * 60,
        httponly=True,
        secure=cookies.secure,
        samesite=samesite_typed,
        domain=cookies.domain,
        path=cookies.path,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    """Logout — delete both cookies. The path/domain MUST match the
    set_cookie call exactly or the browser keeps the old cookie."""
    cookies = settings.cookies
    response.delete_cookie(
        key=cookies.access_name,
        path=cookies.path,
        domain=cookies.domain,
    )
    response.delete_cookie(
        key=cookies.refresh_name,
        path=cookies.path,
        domain=cookies.domain,
    )


def _refresh_token_from_request(
    body_token: str | None, request: Request, settings: Settings
) -> str:
    """Resolve the refresh token: explicit body field wins (for backward
    compat with Bearer-style integrations); otherwise read from the
    HttpOnly cookie. 401 if neither is present."""
    if body_token:
        return body_token
    cookie_value = request.cookies.get(settings.cookies.refresh_name)
    if cookie_value:
        return cookie_value
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing refresh token",
    )


# --- endpoints ----------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenPairResponse,
    summary="Authenticate with email + password.",
    description=(
        "Returns an access token (15 min TTL) and a refresh token (7 day "
        "TTL). The refresh token is single-use: each call to /auth/refresh "
        "rotates it. Replaying a consumed refresh token triggers chain "
        "compromise detection and revokes every session in that family."
    ),
    # Sprint 9.0.6 C — IP cap stops a single host from drowning the
    # auth surface; per-username cap (inside the handler, after parse)
    # prevents an attacker who rotates source IPs from grinding through
    # one specific account. 5/min/IP is generous for honest traffic
    # (most users hit login once per browser session) but bites under
    # credential-stuffing patterns.
    dependencies=[
        Depends(
            rate_limit_ip(
                max_calls=5, window_seconds=60.0, dimension="login_ip"
            )
        )
    ],
    responses={
        401: {"description": "Invalid credentials or inactive user."},
        429: {"description": "Rate limit exceeded."},
    },
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPairResponse:
    """Email + password login. Returns access + refresh token pair."""
    # Per-username limit. Lower-cased so ``Foo@x.com`` and ``foo@x.com``
    # share the same bucket — otherwise the cap is trivially bypassed.
    check_rate_limit(
        "login_username",
        str(body.email).lower(),
        max_calls=10,
        window_seconds=60.0,
    )
    try:
        user, pair = await auth.login(
            email=body.email,
            password=body.password,
            ip_address=_client_ip(request),
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    # Pick the active tenant: explicit > first available > None.
    chosen_tenant_id = body.active_tenant_id
    chosen_role: str | None = None
    if chosen_tenant_id is None:
        tenants = await auth.list_user_tenants(user.id)
        if tenants:
            chosen_tenant_id = tenants[0]["id"]  # type: ignore[assignment]
            chosen_role = str(tenants[0]["role"])
    else:
        # Verify the user is actually linked to the requested tenant.
        tenants = await auth.list_user_tenants(user.id)
        for t in tenants:
            if t["id"] == chosen_tenant_id:
                chosen_role = str(t["role"])
                break
        else:
            if not user.is_super_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="user is not a member of the requested tenant",
                )

    # Re-issue tokens with the chosen tenant context (the first issuance
    # at AuthService.login had no tenant). Cheap: just re-encodes JWTs
    # and writes one extra refresh_token_records row.
    if chosen_tenant_id is not None:
        _user_again, pair = await auth.login(
            email=body.email,
            password=body.password,
            active_tenant_id=chosen_tenant_id,
            active_role=chosen_role,
            ip_address=_client_ip(request),
        )
    _set_auth_cookies(
        response,
        settings,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Rotate the refresh token (single-use chain).",
    description=(
        "Consumes the supplied refresh token and issues a new access + "
        "refresh pair in the same family. Replaying a token that has "
        "already been rotated revokes the entire family — both the "
        "legitimate user's current session and any attacker's stolen copy "
        "are forced to log in again."
    ),
    # Sprint 9.0.6 C — high cap (30/min/IP). Honest clients refresh
    # roughly once per access-token lifetime (15 min) plus retries; a
    # malicious loop trying to brute-force the JTI graph hits this
    # well before it reads anything useful.
    dependencies=[
        Depends(
            rate_limit_ip(
                max_calls=30, window_seconds=60.0, dimension="refresh_ip"
            )
        )
    ],
    responses={
        401: {
            "description": "Token unknown, expired, revoked, or chain compromised."
        },
        429: {"description": "Rate limit exceeded."},
    },
)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPairResponse:
    token = _refresh_token_from_request(body.refresh_token, request, settings)
    try:
        _user, pair = await auth.refresh(token)
    except TokenReuseDetectedError as exc:
        # Same status as a generic invalid token — don't leak detection.
        # Also clear cookies: the family is dead, the browser shouldn't
        # keep posting the now-invalid token on every request.
        _clear_auth_cookies(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid refresh token"
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    _set_auth_cookies(
        response,
        settings,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the refresh token's family. Idempotent.",
    description=(
        "Idempotent: unknown / expired tokens still return 204. After "
        "logout the entire refresh chain is dead — the user must log in "
        "again to obtain new tokens."
    ),
)
async def logout(
    body: LogoutRequest,
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    # Idempotent: if the cookie is already gone we still 204. Treat a
    # missing token as a no-op rather than 401 — the contract is "make
    # sure I'm logged out", and an unauthenticated browser asking that
    # question is fine.
    token = body.refresh_token or request.cookies.get(settings.cookies.refresh_name)
    if token:
        await auth.logout(token)
    _clear_auth_cookies(response, settings)


@router.post(
    "/switch-tenant",
    response_model=TokenPairResponse,
    summary="Re-issue tokens scoped to a different tenant.",
    description=(
        "The user must already be a member of the target tenant (or be a "
        "super-admin). Returns a fresh access + refresh pair in a new "
        "family. The previous family is left intact — call /auth/logout "
        "on it explicitly if you want to retire it."
    ),
    responses={403: {"description": "User is not a member of the requested tenant."}},
)
async def switch_tenant(
    body: SwitchTenantRequest,
    response: Response,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPairResponse:
    """Re-issue tokens with a different active tenant. The user must
    already belong to the target tenant (or be a super-admin)."""
    tenants = await auth.list_user_tenants(current.user_id)
    role: str | None = None
    for t in tenants:
        if t["id"] == body.tenant_id:
            role = str(t["role"])
            break
    if role is None and not current.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not a member of the requested tenant",
        )

    user = await admin_session.get(User, current.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    pair = await auth._issue_token_pair(
        user=user,
        active_tenant_id=body.tenant_id,
        active_role=role,
    )
    _set_auth_cookies(
        response,
        settings,
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Current user, active tenant context, and available tenants.",
    description=(
        "The active context comes from the JWT's active_tenant_id + "
        "active_role claims; available_tenants is the full list of "
        "tenants the user can switch to via /auth/switch-tenant."
    ),
)
async def me(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> MeResponse:
    user = await admin_session.get(User, current.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    tenants = await auth.list_user_tenants(current.user_id)
    if user.is_super_admin:
        # Süper yönetici tüm aktif kurumları görür — switch-tenant zaten
        # üyelik istemiyor, kurum seçici de istememeli. Üyeliği olan
        # kurumda gerçek rolü, olmayanda "super_admin" etiketi döner.
        # Bu birleşim aktif kurumun adını da çözer (eskiden üyelik
        # listesi bulamayınca header "Kurum seçilmedi" gösteriyordu).
        member_ids = {t["id"] for t in tenants}
        rows = await admin_session.execute(
            select(Tenant.id, Tenant.name, Tenant.slug, Tenant.language)
            .where(Tenant.deleted_at.is_(None))
            .order_by(Tenant.name)
        )
        tenants.extend(
            {
                "id": row[0],
                "name": row[1],
                "slug": row[2],
                "role": "super_admin",
                "language": row[3],
            }
            for row in rows.all()
            if row[0] not in member_ids
        )
        tenants.sort(key=lambda t: str(t["name"]).casefold())
    active_tenant_summary: dict[str, Any] | None = None
    if current.active_tenant_id is not None:
        for t in tenants:
            if t["id"] == current.active_tenant_id:
                active_tenant_summary = t
                break
    return MeResponse(
        user=UserSummary(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_super_admin=user.is_super_admin,
        ),
        active_context=ActiveContext(
            tenant_id=current.active_tenant_id,
            tenant_name=str(active_tenant_summary["name"]) if active_tenant_summary else None,
            tenant_slug=str(active_tenant_summary["slug"]) if active_tenant_summary else None,
            role=current.active_role,
            language=str(active_tenant_summary["language"]) if active_tenant_summary else "tr",
        ),
        available_tenants=[
            TenantSummary(
                id=t["id"],  # type: ignore[arg-type]
                name=str(t["name"]),
                slug=str(t["slug"]),
                role=str(t["role"]),
                language=str(t.get("language", "tr")),
            )
            for t in tenants
        ],
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Change the current user's password.",
    description=(
        "Verifies current_password, hashes the new one with argon2, and "
        "bumps users.password_changed_at. Every refresh-token family the "
        "user owns is revoked AND any access token issued before this "
        "moment is rejected by the auth dependency on its next request — "
        "even if its 15-minute expiry has not yet hit."
    ),
    # Sprint 9.0.6 C — IP cap of 5 catches scripts attempting to brute
    # ``current_password``; per-user cap (3/min) inside the handler is
    # the real defence (it survives IP rotation and is keyed on the
    # authenticated user_id).
    dependencies=[
        Depends(
            rate_limit_ip(
                max_calls=5,
                window_seconds=60.0,
                dimension="change_password_ip",
            )
        )
    ],
    responses={
        400: {"description": "Current password does not match."},
        429: {"description": "Rate limit exceeded."},
    },
)
async def change_password(
    body: ChangePasswordRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    check_rate_limit(
        "change_password_user",
        str(current.user_id),
        max_calls=3,
        window_seconds=60.0,
    )
    try:
        await auth.change_password(
            user_id=current.user_id,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# --- helpers ------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
