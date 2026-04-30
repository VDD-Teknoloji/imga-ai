"""TenantConfigService — taxonomy + automation_mode + per-tenant cache.

Owns the read/write paths for tenant-scoped configuration that lives
in the ``categories`` and ``tenant_categories`` tables, plus the
``tenants.automation_mode`` flag. Every mutation:

  1. Validates business rules (e.g. custom code != global code).
  2. Persists.
  3. Writes an audit log entry via AuditService.
  4. Invalidates the per-tenant entry in the injected TTLCache.

The cache is a ``cachetools.TTLCache`` instantiated in the FastAPI
lifespan (``app.state.tenant_config_cache``) and injected here, so
test isolation is achieved by tearing down the FastAPI app, and
multi-process deployments can later swap it for a Redis-backed
cache without touching this service.

A read path (``get_config``) builds a normalized dict of the form::

    {
        "tenant_id": UUID,
        "automation_mode": "manual" | "semi_auto" | "full_auto",
        "categories": [
            {"id": UUID, "code": str, "label_tr": str, "label_en": str | None,
             "description": str | None, "is_global": bool, "is_enabled": bool,
             "is_archived": bool},
            ...
        ],
    }

Disabled (``is_enabled=False``) categories are still returned so the UI
can re-enable them. Soft-deleted custom categories surface with
``is_archived=true`` so historic ticket views can still render the label.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from cachetools import TTLCache
from imga_db.models import (
    AutomationMode,
    Category,
    Tenant,
    TenantCategory,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService


class TenantConfigError(Exception):
    """Generic tenant-config failure (lookup, validation, etc.)."""


class CategoryCodeConflictError(TenantConfigError):
    """A custom category code collides with a global or with the tenant's
    own existing custom category."""


class CategoryNotFoundError(TenantConfigError):
    """The category does not exist, is not visible to this tenant, or
    is already archived."""


class TenantConfigService:
    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService,
        cache: TTLCache[UUID, dict[str, Any]],
    ) -> None:
        self._session = session
        self._audit = audit
        self._cache = cache

    # --- read path ------------------------------------------------------

    async def get_config(self, tenant_id: UUID) -> dict[str, Any]:
        """Return the tenant's full config snapshot. Cached per tenant
        for ttl seconds; mutations call ``_invalidate`` to drop the entry.

        IMPORTANT: this method assumes RLS is already bound on
        ``self._session`` (caller's responsibility). The session is the
        ``app`` role, so categories.RLS will hide other tenants' customs
        and tenant_categories.RLS will hide other tenants' settings.
        """
        cached = self._cache.get(tenant_id)
        if cached is not None:
            return cast(dict[str, Any], cached)

        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None or tenant.deleted_at is not None:
            raise TenantConfigError(f"tenant {tenant_id} not found")

        # Visible categories: globals + this tenant's customs (RLS does
        # the hide-other-tenants work). Archived customs included so the
        # UI can render them with is_archived=true.
        cat_rows = (
            await self._session.execute(
                select(Category).order_by(Category.tenant_id.nulls_first(), Category.code)
            )
        ).scalars().all()

        # Settings only exist for this tenant after RLS.
        setting_rows = (
            await self._session.execute(select(TenantCategory))
        ).scalars().all()
        enabled_by_id: dict[UUID, bool] = {
            s.category_id: s.is_enabled for s in setting_rows
        }

        categories: list[dict[str, Any]] = []
        for cat in cat_rows:
            is_global = cat.tenant_id is None
            # Opt-in semantic: if a tenant doesn't have a row in
            # tenant_categories for a global, treat it as disabled.
            # TenantService.create seeds rows for the globals that exist
            # at creation time; later globals don't auto-enable.
            is_enabled = enabled_by_id.get(cat.id, False)
            categories.append(
                {
                    "id": cat.id,
                    "code": cat.code,
                    "label_tr": cat.label_tr,
                    "label_en": cat.label_en,
                    "description": cat.description,
                    "is_global": is_global,
                    "is_enabled": is_enabled,
                    "is_archived": cat.deleted_at is not None,
                }
            )

        snapshot: dict[str, Any] = {
            "tenant_id": tenant_id,
            "automation_mode": str(tenant.automation_mode),
            "categories": categories,
        }
        self._cache[tenant_id] = snapshot
        return snapshot

    # --- mutations ------------------------------------------------------

    async def set_automation_mode(
        self,
        tenant_id: UUID,
        mode: AutomationMode,
        *,
        actor_user_id: UUID,
    ) -> None:
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None or tenant.deleted_at is not None:
            raise TenantConfigError(f"tenant {tenant_id} not found")

        previous = str(tenant.automation_mode)
        tenant.automation_mode = mode
        await self._session.flush()
        await self._audit.log(
            action="tenant.automation_mode.update",
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={"from": previous, "to": str(mode)},
        )
        self._invalidate(tenant_id)

    async def toggle_category(
        self,
        tenant_id: UUID,
        category_id: UUID,
        *,
        is_enabled: bool,
        actor_user_id: UUID,
    ) -> None:
        """Flip the enabled flag for a (tenant, category) pair.

        Inserts a tenant_categories row on first use (e.g. enabling a
        global the tenant has never touched). Refuses to operate on
        archived custom categories.
        """
        cat = await self._session.get(Category, category_id)
        if cat is None or cat.deleted_at is not None:
            raise CategoryNotFoundError(f"category {category_id} not found")
        # Custom categories from another tenant are filtered by RLS, but
        # globals (tenant_id IS NULL) are visible to everyone — so we
        # only need to guard "wrong tenant" for the case where RLS has
        # been bypassed (e.g. test code using admin session).
        if cat.tenant_id is not None and cat.tenant_id != tenant_id:
            raise CategoryNotFoundError("category belongs to another tenant")

        existing = await self._session.get(TenantCategory, (tenant_id, category_id))
        if existing is None:
            self._session.add(
                TenantCategory(
                    tenant_id=tenant_id,
                    category_id=category_id,
                    is_enabled=is_enabled,
                )
            )
        else:
            existing.is_enabled = is_enabled
        await self._session.flush()
        await self._audit.log(
            action="tenant.category.toggle",
            resource_type="tenant_category",
            resource_id=category_id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={"is_enabled": is_enabled},
        )
        self._invalidate(tenant_id)

    async def create_custom_category(
        self,
        tenant_id: UUID,
        *,
        code: str,
        label_tr: str,
        label_en: str | None = None,
        description: str | None = None,
        actor_user_id: UUID,
    ) -> Category:
        """Create a tenant-scoped custom category.

        Two collision checks:
          1. Code must not match any global (reserved system codes).
          2. Code must not match an existing custom on this tenant
             (DB unique index also catches this; we check first to
             return a friendly error rather than IntegrityError).
        """
        normalized = code.strip().lower()
        if not normalized:
            raise TenantConfigError("category code cannot be empty")

        global_clash = await self._session.execute(
            select(Category.id).where(
                Category.tenant_id.is_(None),
                Category.code == normalized,
                Category.deleted_at.is_(None),
            )
        )
        if global_clash.scalar_one_or_none() is not None:
            raise CategoryCodeConflictError(
                f"code {normalized!r} is a reserved global category"
            )

        own_clash = await self._session.execute(
            select(Category.id).where(
                Category.tenant_id == tenant_id,
                Category.code == normalized,
                Category.deleted_at.is_(None),
            )
        )
        if own_clash.scalar_one_or_none() is not None:
            raise CategoryCodeConflictError(
                f"code {normalized!r} already exists for this tenant"
            )

        cat = Category(
            tenant_id=tenant_id,
            code=normalized,
            label_tr=label_tr,
            label_en=label_en,
            description=description,
        )
        self._session.add(cat)
        await self._session.flush()
        # New custom categories are enabled by default.
        self._session.add(
            TenantCategory(tenant_id=tenant_id, category_id=cat.id, is_enabled=True)
        )
        await self._session.flush()
        await self._audit.log(
            action="tenant.category.create",
            resource_type="category",
            resource_id=cat.id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={"code": normalized},
        )
        self._invalidate(tenant_id)
        return cat

    async def update_custom_category(
        self,
        tenant_id: UUID,
        category_id: UUID,
        *,
        label_tr: str | None = None,
        label_en: str | None = None,
        description: str | None = None,
        actor_user_id: UUID,
    ) -> Category:
        cat = await self._session.get(Category, category_id)
        if cat is None or cat.deleted_at is not None:
            raise CategoryNotFoundError(f"category {category_id} not found")
        if cat.tenant_id != tenant_id:
            raise CategoryNotFoundError("category belongs to another tenant")

        changes: dict[str, Any] = {}
        if label_tr is not None and label_tr != cat.label_tr:
            cat.label_tr = label_tr
            changes["label_tr"] = label_tr
        if label_en is not None and label_en != cat.label_en:
            cat.label_en = label_en
            changes["label_en"] = label_en
        if description is not None and description != cat.description:
            cat.description = description
            changes["description"] = "updated"

        if changes:
            await self._session.flush()
            await self._audit.log(
                action="tenant.category.update",
                resource_type="category",
                resource_id=cat.id,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                details=changes,
            )
            self._invalidate(tenant_id)
        return cat

    async def archive_custom_category(
        self,
        tenant_id: UUID,
        category_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> None:
        """Soft-delete a custom category. Sprint 7.5 will add ON DELETE
        RESTRICT against tickets; for now there are no tickets so a
        soft delete is enough.

        Globals are not archivable (they are system rows).
        """
        cat = await self._session.get(Category, category_id)
        if cat is None or cat.deleted_at is not None:
            raise CategoryNotFoundError(f"category {category_id} not found")
        if cat.tenant_id is None:
            raise TenantConfigError("global categories cannot be archived")
        if cat.tenant_id != tenant_id:
            raise CategoryNotFoundError("category belongs to another tenant")

        cat.deleted_at = datetime.now(UTC)
        # Disabling the link row keeps the classifier from picking it
        # up via the (tenant, category) settings lookup.
        await self._session.execute(
            update(TenantCategory)
            .where(TenantCategory.tenant_id == tenant_id)
            .where(TenantCategory.category_id == category_id)
            .values(is_enabled=False)
        )
        await self._session.flush()
        await self._audit.log(
            action="tenant.category.archive",
            resource_type="category",
            resource_id=category_id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        )
        self._invalidate(tenant_id)

    # --- internals ------------------------------------------------------

    def _invalidate(self, tenant_id: UUID) -> None:
        self._cache.pop(tenant_id, None)
