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

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from imga_db.models import (
    AutomationMode,
    Category,
    CategoryTaxonomy,
    Tenant,
    TenantCategory,
    TenantPlanTier,
)
from imga_db.seeds import DEFAULT_COMPANY_TAXONOMY
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService


class TenantSlugTakenError(ValueError):
    """Raised when a requested slug is already in use."""


class TenantNotFoundError(LookupError):
    """Raised when a tenant lookup fails or the row is soft-deleted."""


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
        language: str = "tr",
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            slug=slug,
            plan_tier=plan_tier,
            automation_mode=automation_mode,
            language=language if language in ("tr", "en") else "tr",
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

        # Sprint 8.3.5. Seed the 21-row default company-perspective
        # taxonomy. Tenant-edit UI lands in 8.3.7; until then this is
        # the static catalog every fresh tenant starts with. Seed
        # mirrors the migration 0017 backfill so existing-tenant rows
        # and new-tenant rows look identical at the schema level.
        for entry in DEFAULT_COMPANY_TAXONOMY:
            self._session.add(
                CategoryTaxonomy(
                    tenant_id=tenant.id,
                    code=entry["code"],
                    label_tr=entry["label_tr"],
                    keywords=list(entry["keywords"]),
                    priority=entry["priority"],
                    primary_category_code=entry["primary_category_code"],
                    is_default_seed=True,
                )
            )
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
                "seeded_taxonomies": len(DEFAULT_COMPANY_TAXONOMY),
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
        name: str | None = None,
        plan_tier: TenantPlanTier | None = None,
        settings: dict[str, Any] | None = None,
        automation_mode: AutomationMode | None = None,
        language: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        """Patch any subset of tenant metadata. ``slug`` is intentionally
        not updatable through this call — slug changes break audit /
        bookmarked URLs and need a dedicated migration helper."""
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None or tenant.deleted_at is not None:
            raise TenantNotFoundError(f"tenant {tenant_id} not found")

        changes: dict[str, Any] = {}
        if name is not None and name != tenant.name:
            tenant.name = name
            changes["name"] = name
        if plan_tier is not None and plan_tier != tenant.plan_tier:
            tenant.plan_tier = plan_tier
            changes["plan_tier"] = str(plan_tier)
        if settings is not None:
            tenant.settings = settings
            changes["settings"] = "updated"
        if automation_mode is not None:
            tenant.automation_mode = automation_mode
            changes["automation_mode"] = str(automation_mode)
        if language is not None and language in ("tr", "en") and language != tenant.language:
            tenant.language = language
            changes["language"] = language

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

    async def list(self, *, include_deleted: bool = False) -> list[Tenant]:
        """All tenants in the system. Super-admin only — caller is
        responsible for the role check."""
        stmt = select(Tenant).order_by(Tenant.created_at.desc())
        if not include_deleted:
            stmt = stmt.where(Tenant.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def soft_delete(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        """Mark the tenant deleted_at=now. Tickets / categories / users
        stay in place (CASCADE is on the FK side, not the soft-delete
        flag), so super-admin can restore by clearing deleted_at via a
        future endpoint or DB op."""
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"tenant {tenant_id} not found")
        if tenant.deleted_at is not None:
            return tenant  # idempotent
        tenant.deleted_at = datetime.now(UTC)
        await self._audit.log(
            action="tenant.delete",
            resource_type="tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            details={"name": tenant.name, "slug": tenant.slug},
        )
        return tenant
