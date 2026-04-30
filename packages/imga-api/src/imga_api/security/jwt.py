"""JWT primitives — encode + decode access and refresh tokens.

Two token types share the same HS256 signing key but carry distinct
payloads. Access tokens are short-lived (15 min default) and embed the
active tenant context so middleware can set RLS without an extra DB
read. Refresh tokens are long-lived (7 days default) and carry only the
identity fields needed for rotation: subject + jti + family + type.

Decoding never returns raw dicts — callers receive a Pydantic model
that constrains shape and pre-validates the `type` field, so a refresh
token cannot be accepted in place of an access token by mistake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

import jwt as pyjwt
from pydantic import BaseModel, ConfigDict, Field

from imga_api.settings import JWTSettings

ACCESS_TOKEN_TYPE: Final[str] = "access"
REFRESH_TOKEN_TYPE: Final[str] = "refresh"


class TokenError(Exception):
    """Raised for any decode/verification failure (expired, invalid, wrong type)."""


# --- payload models ------------------------------------------------------


class AccessTokenPayload(BaseModel):
    """Decoded access token. Carries the active tenant context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sub: UUID = Field(..., description="user_id")
    email: str
    is_super_admin: bool
    active_tenant_id: UUID | None = Field(
        default=None,
        description="None for super-admin actions without a chosen tenant",
    )
    active_role: str | None = None
    type: Literal["access"] = ACCESS_TOKEN_TYPE  # type: ignore[assignment]
    iat: int
    exp: int


class RefreshTokenPayload(BaseModel):
    """Decoded refresh token. Carries only what rotation needs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sub: UUID
    jti: UUID
    family_id: UUID
    type: Literal["refresh"] = REFRESH_TOKEN_TYPE  # type: ignore[assignment]
    iat: int
    exp: int


# --- encoders ------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    *,
    user_id: UUID,
    email: str,
    is_super_admin: bool,
    active_tenant_id: UUID | None,
    active_role: str | None,
    settings: JWTSettings,
    issued_at: datetime | None = None,
) -> tuple[str, AccessTokenPayload]:
    """Encode an access token. Returns (jwt_string, decoded_payload)."""
    iat = issued_at or _now()
    exp = iat + timedelta(minutes=settings.access_token_ttl_minutes)
    raw_payload: dict[str, object] = {
        "sub": str(user_id),
        "email": email,
        "is_super_admin": is_super_admin,
        "active_tenant_id": str(active_tenant_id) if active_tenant_id else None,
        "active_role": active_role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = pyjwt.encode(raw_payload, settings.secret_key, algorithm=settings.algorithm)
    return token, AccessTokenPayload.model_validate(raw_payload)


def create_refresh_token(
    *,
    user_id: UUID,
    jti: UUID,
    family_id: UUID,
    settings: JWTSettings,
    issued_at: datetime | None = None,
) -> tuple[str, RefreshTokenPayload]:
    """Encode a refresh token. Caller is responsible for persisting the jti
    in refresh_token_records before handing the token to the client."""
    iat = issued_at or _now()
    exp = iat + timedelta(days=settings.refresh_token_ttl_days)
    raw_payload: dict[str, object] = {
        "sub": str(user_id),
        "jti": str(jti),
        "family_id": str(family_id),
        "type": REFRESH_TOKEN_TYPE,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = pyjwt.encode(raw_payload, settings.secret_key, algorithm=settings.algorithm)
    return token, RefreshTokenPayload.model_validate(raw_payload)


# --- decoders ------------------------------------------------------------


def _decode_raw(token: str, settings: JWTSettings) -> dict[str, object]:
    try:
        return pyjwt.decode(  # type: ignore[no-any-return]
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"require": ["sub", "type", "iat", "exp"]},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise TokenError(f"invalid token: {exc}") from exc


def decode_access_token(token: str, settings: JWTSettings) -> AccessTokenPayload:
    raw = _decode_raw(token, settings)
    if raw.get("type") != ACCESS_TOKEN_TYPE:
        raise TokenError("expected access token, got different type")
    try:
        return AccessTokenPayload(**raw)  # type: ignore[arg-type]
    except Exception as exc:
        raise TokenError(f"access token shape invalid: {exc}") from exc


def decode_refresh_token(token: str, settings: JWTSettings) -> RefreshTokenPayload:
    raw = _decode_raw(token, settings)
    if raw.get("type") != REFRESH_TOKEN_TYPE:
        raise TokenError("expected refresh token, got different type")
    try:
        return RefreshTokenPayload(**raw)  # type: ignore[arg-type]
    except Exception as exc:
        raise TokenError(f"refresh token shape invalid: {exc}") from exc
