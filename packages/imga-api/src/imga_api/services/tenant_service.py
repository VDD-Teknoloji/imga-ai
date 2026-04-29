"""TenantService — tenant CRUD with slug uniqueness + audit logging.

Note: `tenants` is a global table (no RLS), so slug uniqueness is
enforced at the DB level. Tenant deletion is soft (deleted_at), not
hard, so audit history remains intact.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from imga_db.models import AutomationMode, Tenant, TenantPlanTier
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService


class TenantSlugTakenError(ValueError):
    """Raised when a requested slug is already in use."""


class TenantService:
    def __init__(self, session: AsyncSession, audit: AuditService) -> None:
        self._session = session
        self._audit = audit

    async def create(
        self,
        *,
        name: str,
        slug: str,
        plan_tier: TenantPlanTier = TenantPlanTier.TRIAL,
        automation_mode: AutomationMode = AutomationMode.SEMI_AUTO,
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            slug=slug,
            plan_tier=plan_tier,
            automation_mode=automation_mode,
        )
        self._session.add(tenant)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Caller's `async with session.begin():` will auto-rollback on
            # exit; do not call rollback here or we'd cancel the outer
            # transaction context unexpectedly.
            raise TenantSlugTakenError(f"slug {slug!r} already in use") from exc

        await self._audit.log(
            action="tenant.create",
            resource_type="tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            details={"name": name, "slug": slug, "plan_tier": str(plan_tier)},
        )
        return tenant

    async def get(self, tenant_id: UUID) -> Tenant | None:
        return await self._session.get(Tenant, tenant_id)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        result = await self._session.execute(
            select(Tenant).where(Tenant.slug == slug)
        )
        return result.scalar_one_or_none()

    async def update_settings(
        self,
        tenant_id: UUID,
        *,
        settings: dict[str, Any] | None = None,
        automation_mode: AutomationMode | None = None,
        category_overrides: dict[str, Any] | None = None,
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise LookupError(f"tenant {tenant_id} not found")

        changes: dict[str, Any] = {}
        if settings is not None:
            tenant.settings = settings
            changes["settings"] = "updated"
        if automation_mode is not None:
            tenant.automation_mode = automation_mode
            changes["automation_mode"] = str(automation_mode)
        if category_overrides is not None:
            tenant.category_overrides = category_overrides
            changes["category_overrides"] = "updated"

        if changes:
            await self._audit.log(
                action="tenant.settings.update",
                resource_type="tenant",
                resource_id=tenant.id,
                tenant_id=tenant.id,
                actor_user_id=actor_user_id,
                details=changes,
            )
        return tenant
