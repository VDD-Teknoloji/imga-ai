"""AuthService — login, refresh w/ chain detection, logout, password change.

Refresh-token rotation chain detection:

    issue refresh → row(jti=A, family=F, parent=NULL, used_at=NULL)
    refresh        → row A.used_at=now; new row(jti=B, family=F, parent=A)
    refresh again  → row B.used_at=now; new row(jti=C, family=F, parent=B)

If a token whose ``used_at IS NOT NULL`` is presented again, that's an
attacker replaying a stolen token. We revoke the *entire family* with
reason ``chain_compromise``, killing both the legitimate user and the
attacker. The user has to log in again — annoying but the safe choice.

Logout revokes the family (reason=``logout``); password change revokes
all of the user's families (reason=``password_change``) AND bumps
``users.password_changed_at`` so still-live access tokens issued before
that timestamp are also invalidated by the auth dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from imga_db.models import RefreshTokenRecord, User
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.security import (
    AccessTokenPayload,
    RefreshTokenPayload,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from imga_api.services.audit_service import AuditService
from imga_api.services.user_service import UserService
from imga_api.settings import JWTSettings


class AuthError(Exception):
    """Generic auth failure — credentials, expired, replayed, etc."""


class TokenReuseDetectedError(AuthError):
    """A refresh token marked used was presented again. The family was just revoked."""


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_payload: AccessTokenPayload
    refresh_payload: RefreshTokenPayload


class AuthService:
    """Owns login/refresh/logout/password-change. Uses imga_admin session
    (BYPASSRLS) at the dependency layer because refresh_token_records is
    a global table and tenant context might not be set yet at login.
    """

    def __init__(
        self,
        session: AsyncSession,
        users: UserService,
        audit: AuditService,
        jwt_settings: JWTSettings,
    ) -> None:
        self._session = session
        self._users = users
        self._audit = audit
        self._jwt = jwt_settings

    # --- login ----------------------------------------------------------

    async def login(
        self,
        *,
        email: str,
        password: str,
        active_tenant_id: UUID | None = None,
        active_role: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, TokenPair]:
        user = await self._users.verify_credentials(email, password)
        if user is None:
            await self._audit.log(
                action="auth.login.failed",
                resource_type="user",
                details={"email": email},
                ip_address=ip_address,
            )
            raise AuthError("invalid credentials")

        await self._users.record_login(user.id)
        pair = await self._issue_token_pair(
            user=user,
            active_tenant_id=active_tenant_id,
            active_role=active_role,
        )
        await self._audit.log(
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            actor_user_id=user.id,
            tenant_id=active_tenant_id,
            ip_address=ip_address,
        )
        return user, pair

    # --- refresh w/ chain detection ------------------------------------

    async def refresh(
        self,
        refresh_token: str,
        *,
        active_tenant_id: UUID | None = None,
        active_role: str | None = None,
    ) -> tuple[User, TokenPair]:
        try:
            payload = decode_refresh_token(refresh_token, self._jwt)
        except TokenError as exc:
            raise AuthError(str(exc)) from exc

        record = await self._session.get(RefreshTokenRecord, payload.jti)
        if record is None:
            raise AuthError("refresh token unknown")

        now = datetime.now(UTC)
        if record.revoked_at is not None:
            raise AuthError("refresh token revoked")
        if record.expires_at <= now:
            raise AuthError("refresh token expired")

        # Reuse detection: this token has already been rotated. Treat as
        # compromise and burn the entire family.
        if record.used_at is not None:
            await self._revoke_family(
                record.family_id, reason="chain_compromise", at=now
            )
            await self._audit.log(
                action="auth.refresh.reuse_detected",
                resource_type="refresh_token_family",
                resource_id=record.family_id,
                actor_user_id=record.user_id,
                details={"jti": str(payload.jti)},
            )
            # Persist the revocation BEFORE raising — otherwise the
            # caller's exception-rollback would undo the family revoke
            # and the attacker would still hold a valid token.
            await self._session.commit()
            raise TokenReuseDetectedError(
                "refresh token reuse detected; family revoked"
            )

        # Mark this token rotated and issue a successor in the same family.
        record.used_at = now
        user = await self._session.get(User, record.user_id)
        if user is None or not user.is_active:
            raise AuthError("user inactive")

        # Carry the rotation chain's tenant context across rotations.
        # Explicit kwargs win (kept for symmetry with login); otherwise
        # the new access token mirrors the parent record's claims so
        # silent refreshes don't drop the user's active tenant.
        next_tenant_id = (
            active_tenant_id if active_tenant_id is not None
            else record.active_tenant_id
        )
        next_role = active_role if active_role is not None else record.active_role
        pair = await self._issue_token_pair(
            user=user,
            active_tenant_id=next_tenant_id,
            active_role=next_role,
            family_id=record.family_id,
            parent_jti=record.jti,
        )
        await self._audit.log(
            action="auth.refresh",
            resource_type="refresh_token",
            resource_id=pair.refresh_payload.jti,
            actor_user_id=user.id,
            tenant_id=next_tenant_id,
        )
        return user, pair

    # --- logout ---------------------------------------------------------

    async def logout(self, refresh_token: str) -> None:
        """Revoke the family the refresh token belongs to.

        Tolerant of expired / unknown tokens — logout should be idempotent
        from the client's perspective.
        """
        try:
            payload = decode_refresh_token(refresh_token, self._jwt)
        except TokenError:
            return  # nothing to do; token unparseable

        record = await self._session.get(RefreshTokenRecord, payload.jti)
        if record is None:
            return
        await self._revoke_family(
            record.family_id, reason="logout", at=datetime.now(UTC)
        )
        await self._audit.log(
            action="auth.logout",
            resource_type="refresh_token_family",
            resource_id=record.family_id,
            actor_user_id=record.user_id,
        )

    # --- password change -----------------------------------------------

    async def change_password(
        self,
        *,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> None:
        user = await self._session.get(User, user_id)
        if user is None or not verify_password(current_password, user.password_hash):
            raise AuthError("invalid current password")

        now = datetime.now(UTC)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now

        # Revoke every refresh token family the user owns. Access tokens
        # with iat < password_changed_at are rejected by the dependency.
        await self._session.execute(
            update(RefreshTokenRecord)
            .where(RefreshTokenRecord.user_id == user_id)
            .where(RefreshTokenRecord.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="password_change")
        )

        await self._audit.log(
            action="auth.password.change",
            resource_type="user",
            resource_id=user_id,
            actor_user_id=user_id,
        )

        # Sprint 9.5 C2 — drop the in-memory User row so the next
        # request hits the DB and sees the new password_hash +
        # password_changed_at. Without this, a request that races
        # change_password could be served a stale cached User and
        # the iat-vs-password_changed_at check in get_current_user
        # would compare against the OLD timestamp, accepting a
        # token that should already be invalid.
        from imga_api.auth_deps import invalidate_user_cache
        invalidate_user_cache(user_id)

    # --- internals ------------------------------------------------------

    async def _issue_token_pair(
        self,
        *,
        user: User,
        active_tenant_id: UUID | None,
        active_role: str | None,
        family_id: UUID | None = None,
        parent_jti: UUID | None = None,
    ) -> TokenPair:
        access_token, access_payload = create_access_token(
            user_id=user.id,
            email=user.email,
            is_super_admin=user.is_super_admin,
            active_tenant_id=active_tenant_id,
            active_role=active_role,
            settings=self._jwt,
        )
        new_jti = uuid4()
        new_family = family_id or uuid4()
        refresh_token, refresh_payload = create_refresh_token(
            user_id=user.id,
            jti=new_jti,
            family_id=new_family,
            settings=self._jwt,
        )
        record = RefreshTokenRecord(
            jti=new_jti,
            user_id=user.id,
            family_id=new_family,
            parent_jti=parent_jti,
            issued_at=datetime.fromtimestamp(refresh_payload.iat, tz=UTC),
            expires_at=datetime.fromtimestamp(refresh_payload.exp, tz=UTC),
            active_tenant_id=active_tenant_id,
            active_role=active_role,
        )
        self._session.add(record)
        await self._session.flush()
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_payload=access_payload,
            refresh_payload=refresh_payload,
        )

    async def _revoke_family(
        self,
        family_id: UUID,
        *,
        reason: str,
        at: datetime,
    ) -> None:
        await self._session.execute(
            update(RefreshTokenRecord)
            .where(RefreshTokenRecord.family_id == family_id)
            .where(RefreshTokenRecord.revoked_at.is_(None))
            .values(revoked_at=at, revoke_reason=reason)
        )

    # --- access-token freshness gate (used by FastAPI dependency) ------

    async def is_access_token_fresh(self, payload: AccessTokenPayload) -> bool:
        """Return False when the token was issued at or before the user's
        last password change. Same-second equality is rejected; see the
        ``<=`` rationale in auth_deps.get_current_user."""
        user = await self._session.get(User, payload.sub)
        if user is None or not user.is_active:
            return False
        if user.password_changed_at is None:
            return True
        return payload.iat > int(user.password_changed_at.timestamp())

    # --- /auth/me support ----------------------------------------------

    async def list_user_tenants(self, user_id: UUID) -> list[dict[str, object]]:
        """Return [{tenant_id, tenant_name, tenant_slug, role}, ...] for the
        user. Used by /auth/me and by login when picking a default
        active tenant."""
        from imga_db.models import Tenant, UserTenantLink

        result = await self._session.execute(
            select(
                Tenant.id,
                Tenant.name,
                Tenant.slug,
                UserTenantLink.role,
                Tenant.language,
            )
            .join(UserTenantLink, UserTenantLink.tenant_id == Tenant.id)
            .where(UserTenantLink.user_id == user_id)
            .where(Tenant.deleted_at.is_(None))
            .order_by(Tenant.name)
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "slug": row[2],
                "role": row[3],
                "language": row[4],
            }
            for row in result.all()
        ]
