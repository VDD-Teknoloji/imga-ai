"""İmga v1 partner API auth — çift-yol principal (contract §8/§8.1/§8.6).

Bearer önekine göre yol ayrımı:
  * ``imga_ops_*``           → ops principal (yalnız ``/v1/admin/*``)
  * ``imga_live_``/``imga_stg_`` → tenant principal (``/v1/analyze`` + ``/v1/data``)

- Cross-env (§8.1): token ortamı ≠ sunucu ortamı → 401 ``wrong_environment``.
- Scope çapraz erişim (§8.6): ``require_tenant`` / ``require_ops`` 403 üretir.
- verify() lookup ``imga_admin`` (BYPASSRLS) session ile; tenant principal
  için RLS ``bind_api_tenant`` ile handler'ın transaction'ında bağlanır.

Not: web-app ``get_current_user`` JWT yolundan tamamen AYRI. /v1 yüzeyi
kullanıcı-JWT'si kabul etmez.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from imga_db import set_current_tenant
from imga_db.models import ApiTokenRecord
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import get_settings
from imga_api.db_deps import get_admin_session
from imga_api.security.api_tokens import token_environment
from imga_api.services.api_tokens import ApiTokenService, TokenServiceError
from imga_api.settings import Settings
from imga_api.v1.errors import PartnerApiError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    """/v1 handler'larının aldığı principal."""

    kind: Literal["tenant", "ops"]
    token_id: UUID
    tenant_id: UUID | None  # tenant için dolu, ops için None


def _auth_failed(message: str, *, hint: str | None = None) -> PartnerApiError:
    details = {"hint": hint} if hint else None
    return PartnerApiError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code="auth_failed",
        message=message,
        details=details,
    )


def _server_environment(settings: Settings) -> Literal["live", "stg"]:
    return "live" if settings.environment == "production" else "stg"


async def get_partner_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> ApiPrincipal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _auth_failed("missing bearer token")
    plaintext = creds.credentials

    # Cross-env (§8.1): önek ortamı ↔ sunucu ortamı.
    tok_env = token_environment(plaintext)
    if tok_env is None:
        raise _auth_failed("unrecognized token")
    if tok_env != _server_environment(settings):
        raise _auth_failed("wrong environment", hint="wrong_environment")

    if settings.token_pepper is None:
        # Partner API yapılandırılmamış — sızıntısız 401 (503 detayı vermeden).
        raise _auth_failed("partner api not configured")
    try:
        service = ApiTokenService(
            pepper=settings.token_pepper, environment=settings.environment
        )
    except TokenServiceError as exc:
        raise _auth_failed("partner api misconfigured") from exc

    row = await service.verify(admin_session, plaintext)
    if row is None:
        raise _auth_failed("invalid or revoked token")

    # Principal alanlarını row HÂLÂ yüklüyken çıkar.
    if isinstance(row, ApiTokenRecord):
        principal = ApiPrincipal(kind="tenant", token_id=row.id, tenant_id=row.tenant_id)
        request.state.api_tenant_id = row.tenant_id
    else:
        principal = ApiPrincipal(kind="ops", token_id=row.id, tenant_id=None)
        request.state.api_tenant_id = None

    # verify() bir SELECT koştu → AsyncSession autobegin ile admin_session'da bir
    # transaction AÇIK bıraktı. Bu session FastAPI dependency-cache'iyle
    # /v1/admin/* handler'larıyla PAYLAŞILIR; handler ``async with
    # admin_session.begin()`` çağırınca "A transaction is already begun on this
    # Session" 500'ü patlar (prod C1/C2 bug'ı). Read-transaction'ı burada kapat →
    # paylaşılan session handler'a temiz gider. Read olduğu için rollback kayıpsız;
    # row artık expire olur ama alanları yukarıda okundu.
    await admin_session.rollback()
    return principal


async def require_tenant(
    principal: Annotated[ApiPrincipal, Depends(get_partner_principal)],
) -> ApiPrincipal:
    """/v1/analyze + /v1/data — yalnız tenant scope (§8.6)."""
    if principal.kind != "tenant":
        raise PartnerApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="auth_failed",
            message="ops token cannot access tenant surface",
            details={"hint": "ops_scope_cannot_impersonate_tenant"},
        )
    return principal


async def require_ops(
    principal: Annotated[ApiPrincipal, Depends(get_partner_principal)],
) -> ApiPrincipal:
    """/v1/admin/* — yalnız ops scope (§8.6)."""
    if principal.kind != "ops":
        raise PartnerApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code="auth_failed",
            message="tenant token cannot access admin surface",
            details={"hint": "tenant_scope_cannot_access_admin"},
        )
    return principal


async def bind_api_tenant(
    session: AsyncSession, principal: ApiPrincipal
) -> None:
    """Tenant principal için RLS bind — handler kendi transaction'ında çağırır
    (get_current_user/bind_tenant deseni)."""
    if principal.tenant_id is not None:
        await set_current_tenant(session, principal.tenant_id)


__all__ = [
    "ApiPrincipal",
    "get_partner_principal",
    "require_tenant",
    "require_ops",
    "bind_api_tenant",
]
