"""TenantService — tenant CRUD with slug uniqueness + audit logging.

Note: `tenants` is a global table (no RLS), so slug uniqueness is
enforced at the DB level. Tenant deletion is soft (deleted_at), not
hard, so audit history remains intact.

Tenant creation also seeds ``tenant_categories`` with the eight
globals that exist at creation time (Sprint 7.4 opt-in semantic):
new globals added by future migrations do NOT auto-enable for
existing tenants — they have to opt in via the config API.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from imga_db.models import AutomationMode, Category, Tenant, TenantCategory, TenantPlanTier
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

        # Seed tenant_categories with the globals that exist *now*. New
        # globals added by a future migration are intentionally not auto-
        # enabled for already-existing tenants (opt-in by design).
        global_ids = (
            await self._session.execute(
                select(Category.id).where(
                    Category.tenant_id.is_(None),
                    Category.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for cat_id in global_ids:
            self._session.add(
                TenantCategory(
                    tenant_id=tenant.id,
                    category_id=cat_id,
                    is_enabled=True,
                )
            )
        if global_ids:
            await self._session.flush()

        await self._audit.log(
            action="tenant.create",
            resource_type="tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            details={
                "name": name,
                "slug": slug,
                "plan_tier": str(plan_tier),
                "seeded_categories": len(global_ids),
            },
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
