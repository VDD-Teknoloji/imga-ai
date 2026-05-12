"""Auth dependencies: bearer-token decode, RLS context binding, RBAC.

Wiring per request:

    1. ``get_current_user`` decodes the Bearer JWT, checks expiry,
       checks ``user.password_changed_at`` for staleness, and binds
       ``app.current_tenant_id`` on the imga_app session via
       ``set_current_tenant``.
    2. Endpoint handlers depend on ``get_current_user`` (or a stricter
       wrapper like ``require_role``) and additionally on the appropriate
       DB session dependency.

Super-admin context: when ``is_super_admin=True`` and ``active_tenant_id``
is None, no SET LOCAL is issued and handlers are expected to use the
admin session (BYPASSRLS) rather than the app session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, NamedTuple
from uuid import UUID

from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from imga_db import set_current_tenant
from imga_db.models import User, UserTenantRole
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.db_deps import get_admin_session, get_app_session
from imga_api.security import AccessTokenPayload, TokenError, decode_access_token
from imga_api.services import AuditService, AuthService, UserService
from imga_api.settings import JWTSettings, Settings

_bearer_scheme = HTTPBearer(auto_error=False)


# Sprint 9.5 C2 — per-process TTL cache for the auth-path User lookup.
# Production pg_stat_statements (12.05.2026) showed ~3000 SELECT FROM
# users WHERE id=? calls per snapshot window — each ~0.06-0.23ms, so
# the latency tax per request is sub-millisecond but the volume adds
# up. The cache absorbs the repeats; ``invalidate_user_cache`` is
# called by AuthService.change_password (and future role / deactivate
# endpoints) to bound staleness. TTL is 60s — short enough that an
# operator's password change is felt within a minute even on workers
# that didn't service the change_password call themselves.
#
# IMPORTANT: cache a plain NamedTuple, NOT the ORM ``User`` instance.
# SQLAlchemy ORM rows are bound to the session they were loaded
# from; once the session closes, attribute access on the cached
# instance is undefined (lazy-load triggers on a closed session,
# expire-on-commit semantics, etc.). The auth path only reads two
# fields — ``is_active`` and ``password_changed_at`` — so we cache
# those primitives directly. The first iteration of this cache
# stored the ORM row and cross-tenant tests broke when the cached
# row's session went away.
#
# Caveat: per-process. With N uvicorn workers, the cache lives N
# times; an invalidation on worker A doesn't reach worker B. The TTL
# is the safety net for that.
_USER_CACHE_TTL_SECONDS = 60
_USER_CACHE_MAXSIZE = 10_000


class _UserCacheEntry(NamedTuple):
    """Tiny snapshot of the auth-path-relevant User columns. Stored
    as plain primitives so the cache entry survives across session
    boundaries (the ORM ``User`` doesn't)."""

    is_active: bool
    password_changed_at: datetime | None


_user_cache: TTLCache[UUID, _UserCacheEntry] = TTLCache(
    maxsize=_USER_CACHE_MAXSIZE, ttl=_USER_CACHE_TTL_SECONDS
)


def invalidate_user_cache(user_id: UUID) -> None:
    """Drop the cached User row for the given id. Safe to call when
    the id isn't in the cache (no-op). Auth-state mutations (password
    change, role change, deactivate) should call this so the next
    request hits the DB and sees the new state."""
    _user_cache.pop(user_id, None)


def _reset_user_cache_for_tests() -> None:
    """Test-only helper — fixtures clear the cache between cases so a
    stale User row from test A doesn't bleed into test B."""
    _user_cache.clear()


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Resolved current user — what handlers receive."""

    user_id: UUID
    email: str
    is_super_admin: bool
    active_tenant_id: UUID | None
    active_role: str | None
    payload: AccessTokenPayload


def get_settings(request: Request) -> Settings:
    """Lifted out of the app.state set in lifespan (main.py)."""
    settings: Settings = request.app.state.settings
    return settings


def get_jwt_settings(settings: Annotated[Settings, Depends(get_settings)]) -> JWTSettings:
    return settings.jwt


async def get_current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    app_session: Annotated[AsyncSession, Depends(get_app_session)],
) -> CurrentUser:
    """Decode Bearer JWT, check freshness, bind RLS context.

    Decoding is done with the JWT secret in app.state. User existence and
    activity are read from the admin session (no RLS context yet). When
    the token carries an ``active_tenant_id``, we open a short
    transaction on the app session purely to install ``SET LOCAL
    app.current_tenant_id``. That transaction is rolled back immediately
    because the SET LOCAL would have been discarded on commit anyway —
    callers wrap their own queries in their own ``async with
    session.begin():`` and re-issue the bind via the same helper.
    """
    # Sprint 9.0.6 B — bearer header is the legacy / programmatic path;
    # browser clients now ship the access token via an HttpOnly cookie.
    # Bearer wins when both are present (callers that explicitly attach
    # an Authorization header are signalling they want that exact token).
    raw_token: str | None = None
    if creds is not None and creds.scheme.lower() == "bearer":
        raw_token = creds.credentials
    else:
        cookie_token = request.cookies.get(settings.cookies.access_name)
        if cookie_token:
            raw_token = cookie_token
    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(raw_token, settings.jwt)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Sprint 9.5 C2 — cache only the auth-path fields (is_active +
    # password_changed_at) for 60s so the hot path doesn't re-issue
    # ``SELECT FROM users WHERE id=?`` on every request. Cache miss
    # falls through to the admin session; cache hit serves a stale-
    # bounded snapshot. ``invalidate_user_cache`` is called by
    # password change / future role change endpoints.
    cached = _user_cache.get(payload.sub)
    if cached is None:
        user_row = await admin_session.get(User, payload.sub)
        if user_row is None or not user_row.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="user inactive",
            )
        cached = _UserCacheEntry(
            is_active=user_row.is_active,
            password_changed_at=user_row.password_changed_at,
        )
        _user_cache[payload.sub] = cached
    elif not cached.is_active:
        # Cached deactivation — still bounce. The deactivate endpoint
        # SHOULD also invalidate the cache (so the next request hits
        # the DB and re-confirms), but we belt-and-suspenders the
        # check here for defense in depth.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user inactive",
        )
    # `<=`, not `<`: JWT iat is second-precision. A token issued in the
    # same wall-clock second as a password change must also be rejected;
    # otherwise an attacker who races change_password keeps the old
    # access token alive until exp.
    if cached.password_changed_at is not None and payload.iat <= int(
        cached.password_changed_at.timestamp()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token issued before last password change",
        )

    # Stash on request.state so handlers can re-bind in their own
    # transaction without re-decoding the JWT.
    request.state.active_tenant_id = payload.active_tenant_id

    return CurrentUser(
        user_id=payload.sub,
        email=payload.email,
        is_super_admin=payload.is_super_admin,
        active_tenant_id=payload.active_tenant_id,
        active_role=payload.active_role,
        payload=payload,
    )


async def bind_tenant(
    session: AsyncSession,
    current_user: CurrentUser,
) -> None:
    """Helper for handlers: call inside ``async with session.begin():``
    to install the RLS context for the active tenant. No-op for
    super-admin sessions without a chosen tenant."""
    if current_user.active_tenant_id is None:
        return
    await set_current_tenant(session, current_user.active_tenant_id)


def require_role(
    *allowed: UserTenantRole,
) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    """Dependency factory: 403 unless the current user has one of the
    listed roles, or is a super-admin (which always passes)."""
    allowed_str = {str(r) for r in allowed}

    async def _checker(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if user.is_super_admin:
            return user
        if user.active_role is None or user.active_role not in allowed_str:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
        return user

    return _checker


async def require_super_admin(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if not user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="super admin required",
        )
    return user


def get_auth_service(
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    settings_jwt: Annotated[JWTSettings, Depends(get_jwt_settings)],
) -> AuthService:
    """Auth uses the admin (BYPASSRLS) session because
    refresh_token_records is global and tenant context isn't established
    at login."""
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    return AuthService(admin_session, users, audit, settings_jwt)
