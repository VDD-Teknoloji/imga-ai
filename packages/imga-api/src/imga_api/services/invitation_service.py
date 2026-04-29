"""InvitationService — secure-token invitation flow with idempotent accept.

Design:
  1. Tenant admin calls ``create_invitation``: a 256-bit random token is
     generated; the SHA-256 hash is persisted; the plaintext token is
     returned to the caller exactly once for embedding in the email link.
  2. Recipient submits the plaintext token + new password to
     ``accept_invitation``: the token is hashed and looked up, expiry is
     checked, and the row is atomically marked accepted via a conditional
     UPDATE on ``accepted_at IS NULL`` (prevents race + replay).
  3. On accept the User is created (if needed) and linked to the tenant
     with the role recorded on the invitation.

The plaintext token never lives in the DB; a DB compromise alone cannot
forge an acceptance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from imga_db.models import Invitation, User, UserTenantRole
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.security import generate_invitation_token, hash_token
from imga_api.services.audit_service import AuditService
from imga_api.services.user_service import UserService

INVITATION_TTL: Final[timedelta] = timedelta(days=7)


class InvitationAcceptanceError(Exception):
    """Raised when an invitation token is invalid, expired, or replayed."""


class InvitationService:
    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService,
        user_service: UserService,
    ) -> None:
        self._session = session
        self._audit = audit
        self._users = user_service

    # --- create ---------------------------------------------------------

    async def create_invitation(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: UserTenantRole,
        invited_by: UUID,
        ttl: timedelta = INVITATION_TTL,
    ) -> tuple[Invitation, str]:
        """Persist an invitation row + return (Invitation, plaintext_token).

        The plaintext token is returned exactly once and must be sent to
        the invitee out-of-band (email link). It is never stored.
        """
        plaintext, token_hash = generate_invitation_token()
        invitation = Invitation(
            tenant_id=tenant_id,
            email=email.lower().strip(),
            role=role,
            token_hash=token_hash,
            invited_by=invited_by,
            expires_at=datetime.now(UTC) + ttl,
        )
        self._session.add(invitation)
        await self._session.flush()

        await self._audit.log(
            action="invitation.create",
            resource_type="invitation",
            resource_id=invitation.id,
            tenant_id=tenant_id,
            actor_user_id=invited_by,
            details={"email": invitation.email, "role": str(role)},
        )
        return invitation, plaintext

    # --- accept ---------------------------------------------------------

    async def accept_invitation(
        self,
        *,
        plaintext_token: str,
        full_name: str,
        password: str,
    ) -> tuple[User, Invitation]:
        """Atomically claim an invitation, create user, attach to tenant.

        Race protection: the UPDATE WHERE accepted_at IS NULL guarantees
        that two concurrent acceptances of the same token cannot both win
        — one row update count is 1, the other is 0 and raises.
        """
        token_hash = hash_token(plaintext_token)
        now = datetime.now(UTC)

        # Atomic claim: returns 1 row when this caller wins the race.
        stmt = (
            update(Invitation)
            .where(
                Invitation.token_hash == token_hash,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > now,
            )
            .values(accepted_at=now)
            .returning(
                Invitation.id,
                Invitation.tenant_id,
                Invitation.email,
                Invitation.role,
                Invitation.invited_by,
            )
        )
        result = await self._session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            # Not found, expired, or already accepted — keep the error
            # message generic so attackers can't probe for valid tokens.
            raise InvitationAcceptanceError("invitation invalid, expired, or already accepted")

        invitation_id, tenant_id, email, role, invited_by = row

        # Reuse an existing user with this email if one exists; otherwise
        # create a new one. Either way, attach to the tenant with the
        # invitation's role.
        existing = await self._users.get_by_email(email)
        if existing is None:
            user = await self._users.create(
                email=email,
                password=password,
                full_name=full_name,
                actor_user_id=invited_by,
            )
        else:
            # Existing identity: do NOT change their password silently.
            user = existing

        await self._users.attach_to_tenant(
            user_id=user.id,
            tenant_id=tenant_id,
            role=UserTenantRole(role),
            invited_by_user_id=invited_by,
            invitation_accepted_at=now,
        )

        # session.get() may return a stale copy from the identity map
        # because the UPDATE...RETURNING above bypassed ORM tracking. Refresh
        # so callers observe accepted_at = now rather than NULL.
        invitation = await self._session.get(Invitation, invitation_id)
        assert invitation is not None
        await self._session.refresh(invitation)

        await self._audit.log(
            action="invitation.accept",
            resource_type="invitation",
            resource_id=invitation_id,
            tenant_id=tenant_id,
            actor_user_id=user.id,
            details={"email": email, "role": str(role)},
        )
        return user, invitation
