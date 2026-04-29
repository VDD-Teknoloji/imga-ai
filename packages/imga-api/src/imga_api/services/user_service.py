"""UserService — user CRUD + password lifecycle + tenant link management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from imga_db.models import User, UserTenantLink, UserTenantRole
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.security import hash_password, needs_rehash, verify_password
from imga_api.services.audit_service import AuditService


class EmailTakenError(ValueError):
    """Raised when create() is called with an email already on file."""


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
