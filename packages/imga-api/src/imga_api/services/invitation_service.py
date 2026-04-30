"""InvitationService — secure-token invitation flow with idempotent accept.

Design:
  1. Tenant admin calls ``create_invitation``: a 256-bit random token is
     generated; the SHA-256 hash is persisted; the plaintext token is
     returned to the caller exactly once for embedding in the email link.
  2. Recipient submits the plaintext token + new password to
     ``accept_invitation`` (legacy single-call) or
     ``accept_invitation_for_new_user`` / ``accept_invitation_for_existing_user``
     (Sprint 7.5.5 split — strict separation between create-new-account
     and join-tenant-as-existing-user flows).
  3. The atomic claim is shared by all three paths: a conditional UPDATE
     on ``accepted_at IS NULL`` guarantees a single winner among
     concurrent acceptances.

The plaintext token never lives in the DB; a DB compromise alone cannot
forge an acceptance.

Revoke is a hard DELETE rather than a flag column. Audit history is
preserved by ``audit_logs`` (``invitation.revoke`` row); the live
``invitations`` table only tracks open invitations, which keeps the
atomic-claim query simple (no extra WHERE revoked_at IS NULL).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from imga_db.models import Invitation, Tenant, User, UserTenantRole
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.security import generate_invitation_token, hash_token, verify_password
from imga_api.services.audit_service import AuditService
from imga_api.services.user_service import UserService

INVITATION_TTL: Final[timedelta] = timedelta(days=7)


class InvitationAcceptanceError(Exception):
    """Raised when an invitation token is invalid, expired, or replayed."""


class InvitationEmailMismatchError(InvitationAcceptanceError):
    """Existing-user accept path: the JWT user does not match the email
    the invitation was issued to."""


class InvitationEmailExistsError(InvitationAcceptanceError):
    """New-user accept path: email is already on file. Caller should
    use the existing-user accept endpoint instead."""


class InvitationReauthFailedError(InvitationAcceptanceError):
    """Existing-user accept path: re-auth password did not match."""


@dataclass(frozen=True, slots=True)
class InvitationPreview:
    """Read-only snapshot of an invitation for the preview endpoint.
    Carries no token or hash — callers display tenant + role to the
    invitee before they fill out the accept form."""

    tenant_id: UUID
    tenant_name: str
    invited_email: str
    role: UserTenantRole
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _ClaimedInvitation:
    """Internal shape returned by the atomic claim helper."""

    invitation_id: UUID
    tenant_id: UUID
    email: str
    role: UserTenantRole
    invited_by: UUID | None


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
        invited_by: UUID | None,
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

    # --- read -----------------------------------------------------------

    async def list_for_tenant(
        self,
        tenant_id: UUID,
        *,
        include_accepted: bool = False,
    ) -> list[Invitation]:
        """Pending (and optionally already-accepted) invitations for a
        tenant. Caller is responsible for the role check."""
        stmt = (
            select(Invitation)
            .where(Invitation.tenant_id == tenant_id)
            .order_by(Invitation.created_at.desc())
        )
        if not include_accepted:
            stmt = stmt.where(Invitation.accepted_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def preview(self, plaintext_token: str) -> InvitationPreview:
        """Look up a token's metadata without claiming it. The endpoint
        wrapping this method must be rate-limited (token + IP) — the
        generic error message keeps an attacker from probing valid
        tokens, but high-volume guessing would still be a budget drain
        on the DB layer.

        Note: SELECT only — does NOT race-protect against subsequent
        accept calls. The point of preview is to surface "is this link
        worth filling out the form for"."""
        token_hash = hash_token(plaintext_token)
        now = datetime.now(UTC)

        stmt = (
            select(
                Invitation.id,
                Invitation.tenant_id,
                Invitation.email,
                Invitation.role,
                Invitation.expires_at,
                Invitation.accepted_at,
                Tenant.name,
            )
            .join(Tenant, Tenant.id == Invitation.tenant_id)
            .where(Invitation.token_hash == token_hash)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            raise InvitationAcceptanceError("invitation invalid, expired, or already accepted")
        _invitation_id, tenant_id, email, role, expires_at, accepted_at, tenant_name = row
        if accepted_at is not None or expires_at <= now:
            raise InvitationAcceptanceError("invitation invalid, expired, or already accepted")
        return InvitationPreview(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            invited_email=email,
            role=UserTenantRole(role),
            expires_at=expires_at,
        )

    # --- revoke ---------------------------------------------------------

    async def revoke(
        self,
        invitation_id: UUID,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
    ) -> None:
        """Hard-delete the invitation row + write an audit entry. Caller
        guarantees the actor has rights over ``tenant_id`` (super-admin
        or tenant_admin of that tenant)."""
        invitation = await self._session.get(Invitation, invitation_id)
        if invitation is None or invitation.tenant_id != tenant_id:
            raise LookupError(f"invitation {invitation_id} not found in tenant")

        await self._audit.log(
            action="invitation.revoke",
            resource_type="invitation",
            resource_id=invitation.id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={
                "email": invitation.email,
                "role": str(invitation.role),
                "was_accepted": invitation.accepted_at is not None,
            },
        )
        await self._session.delete(invitation)
        await self._session.flush()

    # --- accept (atomic claim shared by both new + existing paths) ----

    async def _claim(self, plaintext_token: str, now: datetime) -> _ClaimedInvitation:
        """Single-use atomic claim. Sets accepted_at=now exactly once;
        concurrent claimers see no row and raise."""
        token_hash = hash_token(plaintext_token)
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
            raise InvitationAcceptanceError(
                "invitation invalid, expired, or already accepted"
            )
        invitation_id, tenant_id, email, role, invited_by = row
        return _ClaimedInvitation(
            invitation_id=invitation_id,
            tenant_id=tenant_id,
            email=email,
            role=UserTenantRole(role),
            invited_by=invited_by,
        )

    async def accept_invitation(
        self,
        *,
        plaintext_token: str,
        full_name: str,
        password: str,
    ) -> tuple[User, Invitation]:
        """Legacy auto-pick accept. Kept for the existing test suite +
        the original Sprint 7.3 flow. New code should prefer
        ``accept_invitation_for_new_user`` (raises on existing email)
        or ``accept_invitation_for_existing_user`` (re-auths)."""
        now = datetime.now(UTC)
        claimed = await self._claim(plaintext_token, now)

        existing = await self._users.get_by_email(claimed.email)
        if existing is None:
            user = await self._users.create(
                email=claimed.email,
                password=password,
                full_name=full_name,
                actor_user_id=claimed.invited_by,
            )
        else:
            user = existing

        await self._users.attach_to_tenant(
            user_id=user.id,
            tenant_id=claimed.tenant_id,
            role=claimed.role,
            invited_by_user_id=claimed.invited_by,
            invitation_accepted_at=now,
        )

        invitation = await self._session.get(Invitation, claimed.invitation_id)
        assert invitation is not None
        await self._session.refresh(invitation)

        await self._audit.log(
            action="invitation.accept",
            resource_type="invitation",
            resource_id=claimed.invitation_id,
            tenant_id=claimed.tenant_id,
            actor_user_id=user.id,
            details={"email": claimed.email, "role": str(claimed.role)},
        )
        return user, invitation

    async def accept_invitation_for_new_user(
        self,
        *,
        plaintext_token: str,
        full_name: str,
        password: str,
    ) -> tuple[User, Invitation]:
        """Sprint 7.5.5 strict-new-user path. If the email already
        belongs to a user the claim is rolled back via raise so the
        recipient can re-submit through the existing-user endpoint."""
        # Pre-flight check first — the existing-user case is a
        # 409 from the API's POV, not a token-claim-failed case, so we
        # don't want to consume the single-use token for it.
        token_hash_email = hash_token(plaintext_token)
        invited_email_row = await self._session.execute(
            select(Invitation.email)
            .where(Invitation.token_hash == token_hash_email)
            .where(Invitation.accepted_at.is_(None))
        )
        invited_email = invited_email_row.scalar_one_or_none()
        if invited_email is not None:
            existing = await self._users.get_by_email(invited_email)
            if existing is not None:
                raise InvitationEmailExistsError(
                    "email already registered; use the existing-user accept endpoint"
                )

        return await self.accept_invitation(
            plaintext_token=plaintext_token,
            full_name=full_name,
            password=password,
        )

    async def accept_invitation_for_existing_user(
        self,
        *,
        plaintext_token: str,
        current_user_id: UUID,
        password_for_reauth: str,
    ) -> Invitation:
        """Sprint 7.5.5 existing-user path. Re-verifies the user's
        current password before claiming the token, so a stolen
        invitation link cannot silently bind itself to an authenticated
        session."""
        current_user = await self._users.get(current_user_id)
        if current_user is None:
            raise InvitationAcceptanceError("invitation invalid, expired, or already accepted")
        if not verify_password(password_for_reauth, current_user.password_hash):
            raise InvitationReauthFailedError("password does not match")

        now = datetime.now(UTC)
        claimed = await self._claim(plaintext_token, now)

        # Email on the invitation must match the authenticated user's
        # email, otherwise an Acme admin could phish a Beta member into
        # joining the wrong tenant by sharing a token URL.
        if claimed.email != current_user.email:
            raise InvitationEmailMismatchError(
                "invitation was issued to a different email"
            )

        await self._users.attach_to_tenant(
            user_id=current_user.id,
            tenant_id=claimed.tenant_id,
            role=claimed.role,
            invited_by_user_id=claimed.invited_by,
            invitation_accepted_at=now,
        )

        invitation = await self._session.get(Invitation, claimed.invitation_id)
        assert invitation is not None
        await self._session.refresh(invitation)

        await self._audit.log(
            action="invitation.accept",
            resource_type="invitation",
            resource_id=claimed.invitation_id,
            tenant_id=claimed.tenant_id,
            actor_user_id=current_user.id,
            details={
                "email": claimed.email,
                "role": str(claimed.role),
                "flow": "existing_user",
            },
        )
        return invitation
