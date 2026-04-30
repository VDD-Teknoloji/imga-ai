"""Public invitation endpoints — preview + accept (new + existing user).

Three routes that ride a 256-bit URL-path token. Two are
unauthenticated; the third (accept-existing) reuses the bearer-token
auth dep but also re-verifies password before claiming.

Rate limiting: every route stacks two slowapi limiters — one keyed
by IP (10/min) and one keyed by the path token (5/min). Generic
errors keep an attacker from probing token validity.

Attack surface notes:

  * /preview is read-only and does NOT consume the token. It exists
    so the frontend can show "this invitation is for you, expires X"
    without committing. A thousand previews don't burn the token.
  * /accept and /accept-existing are single-use atomic claims via
    InvitationService._claim. Concurrent acceptances see a single
    winner; the others get the generic "invalid or expired" error.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.auth_deps import CurrentUser, get_auth_service, get_current_user
from imga_api.db_deps import get_admin_session
from imga_api.rate_limit import rate_limit_ip, rate_limit_token
from imga_api.services import (
    AuditService,
    AuthService,
    InvitationAcceptanceError,
    InvitationEmailExistsError,
    InvitationEmailMismatchError,
    InvitationReauthFailedError,
    InvitationService,
    UserService,
)

router = APIRouter(prefix="/invitations", tags=["Auth"])

# Stacked rate limit dependencies — IP (10/min) + token (5/min). Both
# fire as FastAPI Depends so the route's Annotated[Depends(...)]
# parameters keep their introspection.
_ip_limit = Depends(rate_limit_ip(max_calls=10, window_seconds=60))
_token_limit = Depends(rate_limit_token(max_calls=5, window_seconds=60))


# --- request / response models ----------------------------------------


class InvitationPreviewResponse(BaseModel):
    tenant_id: UUID
    tenant_name: str
    invited_email: str
    role: str
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)


class InvitationAcceptExistingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(..., min_length=1, max_length=256)


class InvitationAcceptResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


# --- helpers ----------------------------------------------------------


def _generic_invitation_error() -> HTTPException:
    """Keep the wire-level error opaque to defeat token probing. Both
    "wrong token" and "expired" surface the same way."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="invitation invalid, expired, or already accepted",
    )


# --- preview ----------------------------------------------------------


@router.post(
    "/{token}/preview",
    response_model=InvitationPreviewResponse,
    summary="Inspect an invitation without consuming it.",
    dependencies=[_ip_limit, _token_limit],
)
async def preview_invitation(
    token: str,
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> InvitationPreviewResponse:
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)

    try:
        preview = await invitations.preview(token)
    except InvitationAcceptanceError as exc:
        raise _generic_invitation_error() from exc
    return InvitationPreviewResponse(
        tenant_id=preview.tenant_id,
        tenant_name=preview.tenant_name,
        invited_email=preview.invited_email,
        role=str(preview.role),
        expires_at=preview.expires_at,
    )


# --- accept (new user) ------------------------------------------------


@router.post(
    "/{token}/accept",
    response_model=InvitationAcceptResponse,
    summary="Create a new account from an invitation.",
    description=(
        "If the invitation email already belongs to a registered user, "
        "this endpoint returns 409 — call /accept-existing with bearer "
        "auth instead. The single-use token is NOT consumed in the "
        "409 path."
    ),
    responses={
        404: {"description": "Invalid / expired / already accepted."},
        409: {"description": "Email already registered; use accept-existing."},
    },
    dependencies=[_ip_limit, _token_limit],
)
async def accept_invitation(
    token: str,
    body: InvitationAcceptRequest,
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> InvitationAcceptResponse:
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)

    try:
        user, _invitation = await invitations.accept_invitation_for_new_user(
            plaintext_token=token,
            full_name=body.full_name,
            password=body.password,
        )
    except InvitationEmailExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except InvitationAcceptanceError as exc:
        raise _generic_invitation_error() from exc

    # Issue a token pair for the freshly minted account so the frontend
    # can drop them straight into the dashboard.
    pair = await auth._issue_token_pair(
        user=user,
        active_tenant_id=None,  # fresh user; let /auth/me + switch-tenant pick the default
        active_role=None,
    )
    return InvitationAcceptResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )


# --- accept-existing (auth required) -----------------------------------


@router.post(
    "/{token}/accept-existing",
    response_model=InvitationAcceptResponse,
    summary="Attach an existing authenticated user to a new tenant.",
    description=(
        "Requires bearer auth (the caller is already logged in). The "
        "request body re-supplies the password as a defence-in-depth "
        "step against a stolen invitation link silently binding to "
        "another user's session."
    ),
    responses={
        401: {"description": "Re-auth password did not match."},
        403: {"description": "Invitation was issued to a different email."},
        404: {"description": "Invalid / expired / already accepted."},
    },
    dependencies=[_ip_limit, _token_limit],
)
async def accept_invitation_existing(
    token: str,
    body: InvitationAcceptExistingRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> InvitationAcceptResponse:
    audit = AuditService(admin_session)
    users = UserService(admin_session, audit)
    invitations = InvitationService(admin_session, audit, users)

    try:
        await invitations.accept_invitation_for_existing_user(
            plaintext_token=token,
            current_user_id=current.user_id,
            password_for_reauth=body.password,
        )
    except InvitationReauthFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        ) from exc
    except InvitationEmailMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except InvitationAcceptanceError as exc:
        raise _generic_invitation_error() from exc

    # Re-issue tokens so the new tenant appears in /auth/me's
    # available_tenants without a logout cycle.
    from imga_db.models import User as UserModel
    user_obj = await admin_session.get(UserModel, current.user_id)
    assert user_obj is not None
    pair = await auth._issue_token_pair(
        user=user_obj,
        active_tenant_id=current.active_tenant_id,
        active_role=current.active_role,
    )
    return InvitationAcceptResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
    )
