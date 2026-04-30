"""UserService — user CRUD + password lifecycle + tenant link management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from imga_db.models import User, UserTenantLink, UserTenantRole
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.security import hash_password, needs_rehash, verify_password
from imga_api.services.audit_service import AuditService


class EmailTakenError(ValueError):
    """Raised when create() is called with an email already on file."""


@dataclass(frozen=True, slots=True)
class TenantMember:
    """Wire-shape view of a tenant member for the directory endpoint.

    A flat dataclass (rather than a dict or two-row tuple) so callers
    get type-checked field access and the route's response_model maps
    cleanly. ``last_login_at`` is None for users who have never logged
    in (e.g. accepted-invite-but-never-clicked-after) — the UI should
    show a dash, not a fake timestamp."""

    user_id: UUID
    email: str
    full_name: str
    role: UserTenantRole
    is_active: bool
    last_login_at: datetime | None
    invitation_accepted_at: datetime | None


class UserService:
    def __init__(self, session: AsyncSession, audit: AuditService) -> None:
        self._session = session
        self._audit = audit

    # --- creation -------------------------------------------------------

    async def create(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        is_super_admin: bool = False,
        actor_user_id: UUID | None = None,
    ) -> User:
        user = User(
            email=email.lower().strip(),
            password_hash=hash_password(password),
            full_name=full_name,
            is_super_admin=is_super_admin,
        )
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Same convention as TenantService: do not rollback here.
            raise EmailTakenError(f"email {email!r} already in use") from exc

        await self._audit.log(
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            actor_user_id=actor_user_id,
            details={"email": user.email, "is_super_admin": is_super_admin},
        )
        return user

    # --- read -----------------------------------------------------------

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    # --- password lifecycle --------------------------------------------

    async def verify_credentials(self, email: str, password: str) -> User | None:
        """Verify email + password, return user on match else None.

        Side effect: rehashes the password with current argon2 params if
        the stored hash is outdated, so we silently raise the security
        floor when the library updates defaults.
        """
        user = await self.get_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        return user

    async def change_password(
        self,
        user_id: UUID,
        new_password: str,
        *,
        actor_user_id: UUID | None = None,
    ) -> User:
        user = await self._session.get(User, user_id)
        if user is None:
            raise LookupError(f"user {user_id} not found")
        user.password_hash = hash_password(new_password)
        await self._audit.log(
            action="user.password.change",
            resource_type="user",
            resource_id=user.id,
            actor_user_id=actor_user_id or user_id,
        )
        return user

    async def record_login(self, user_id: UUID) -> None:
        user = await self._session.get(User, user_id)
        if user is None:
            return
        user.last_login_at = datetime.now(UTC)

    # --- tenant membership ---------------------------------------------

    async def list_for_tenant(
        self,
        tenant_id: UUID,
        *,
        search: str | None = None,
    ) -> list[TenantMember]:
        """Return active members of the tenant.

        Sprint 7.5.5 / Alt-Faz 4 (A7). The frontend ticket-detail
        assignee picker reads this; the route auth allows any tenant
        member to read so VIEWER can also see "who else is here".

        Soft-deleted users are excluded. ``search`` filters on
        case-insensitive email or full_name substring.
        """
        stmt = (
            select(User, UserTenantLink)
            .join(UserTenantLink, UserTenantLink.user_id == User.id)
            .where(UserTenantLink.tenant_id == tenant_id)
            .where(User.deleted_at.is_(None))
            .order_by(User.full_name.asc())
        )
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.email.ilike(pattern),
                    User.full_name.ilike(pattern),
                )
            )
        rows = (await self._session.execute(stmt)).all()
        return [
            TenantMember(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=link.role,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
                invitation_accepted_at=link.invitation_accepted_at,
            )
            for user, link in rows
        ]

    async def attach_to_tenant(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: UserTenantRole,
        invited_by_user_id: UUID | None = None,
        invitation_accepted_at: datetime | None = None,
        actor_user_id: UUID | None = None,
    ) -> UserTenantLink:
        link = UserTenantLink(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            invited_by_user_id=invited_by_user_id,
            invitation_accepted_at=invitation_accepted_at,
        )
        self._session.add(link)
        await self._session.flush()
        await self._audit.log(
            action="user_tenant.attach",
            resource_type="user_tenant",
            tenant_id=tenant_id,
            actor_user_id=actor_user_id or invited_by_user_id,
            details={"user_id": str(user_id), "role": str(role)},
        )
        return link
