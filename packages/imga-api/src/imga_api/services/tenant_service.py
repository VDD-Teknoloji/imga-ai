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

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from imga_db.models import (
    AnalyzeBatchJob,
    AutomationMode,
    Category,
    CategoryTaxonomy,
    LlmCallAudit,
    Review,
    Tenant,
    TenantCategory,
    TenantEngagementSetting,
    TenantMonthlyMetric,
    TenantPlanTier,
)
from imga_db.seeds import DEFAULT_COMPANY_TAXONOMY
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.services.engagement_service import (
    DEFAULT_BANDS,
    add_months,
    compute_engagement_pct,
    normalize_month,
    resolve_band,
)

_COST_WINDOW_DAYS = 30


class TenantSlugTakenError(ValueError):
    """Raised when a requested slug is already in use."""


class TenantNotFoundError(LookupError):
    """Raised when a tenant lookup fails or the row is soft-deleted."""


@dataclass(frozen=True, slots=True)
class TenantListRow:
    """One ``list()`` row: the ORM ``Tenant`` + the C3/B7 super-admin
    inventory metrics (2026-08-20). ``engagement_band`` is the CURRENT
    month's band label, computed by re-using (not copying)
    ``engagement_service.compute_engagement_pct`` / ``resolve_band`` —
    same math the per-tenant engagement table uses, applied here to
    every tenant in one pass so the list endpoint stays one query."""

    tenant: Tenant
    review_count: int
    last_upload_at: datetime | None
    tokens_30d: int
    cost_30d_usd: Decimal | None
    engagement_band: str | None


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
        # 2026-08-18 (WS1 onboarding) — opsiyonel profil alanları.
        # Boş bırakılırsa Tenant modelinin varsayılanı (None) geçerli
        # olur; sonradan /settings/profile'dan doldurulabilir.
        industry: str | None = None,
        industry_other_text: str | None = None,
        company_size: str | None = None,
        business_description: str | None = None,
        terminology: list[dict[str, Any]] | None = None,
        actor_user_id: UUID | None = None,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            slug=slug,
            plan_tier=plan_tier,
            automation_mode=automation_mode,
            language=language if language in ("tr", "en") else "tr",
            industry=industry,
            industry_other_text=industry_other_text,
            company_size=company_size,
            business_description=business_description,
            terminology=terminology,
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
            (
                await self._session.execute(
                    select(Category.id).where(
                        Category.tenant_id.is_(None),
                        Category.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
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
        result = await self._session.execute(select(Tenant).where(Tenant.slug == slug))
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

    async def _bulk_bands(self, tenant_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
        """Per-tenant band overrides for every id in one query. Tenants
        without a row fall back to ``DEFAULT_BANDS`` in the caller —
        mirrors ``EngagementService.get_bands`` (not reused directly:
        that method is one-tenant-at-a-time by design, see its own
        docstring; re-implementing the same one-line fallback here is
        cheaper than adding a bulk variant to EngagementService for a
        single caller).

        NOTE: this must stay defined BEFORE ``list`` below. A method
        named ``list`` on this class shadows the builtin ``list[...]``
        generic for annotations in methods that follow it in the same
        class body (mypy resolves the bare name against the class
        namespace being built so far) — moving this after ``list``
        makes ``list[dict[str, Any]]`` above resolve to
        ``TenantService.list`` instead of the builtin and mypy rejects
        it with "Function ... is not valid as a type"."""
        if not tenant_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    TenantEngagementSetting.tenant_id,
                    TenantEngagementSetting.bands,
                ).where(TenantEngagementSetting.tenant_id.in_(tenant_ids))
            )
        ).all()
        return {tenant_id: list(bands) for tenant_id, bands in rows if bands}

    async def list(self, *, include_deleted: bool = False) -> list[TenantListRow]:
        """All tenants in the system + the C3/B7 inventory metrics
        (review_count, last_upload_at, tokens_30d, cost_30d_usd,
        engagement_band). Super-admin only — caller is responsible for
        the role check.

        Two queries total, neither per-tenant (no N+1): one main
        SELECT with LEFT JOIN aggregate subqueries covers everything
        except the band label (JSONB, can't be resolved in SQL — a
        second bulk SELECT fetches per-tenant band overrides and the
        band itself is computed in Python via
        ``engagement_service.resolve_band``).
        """
        cost_cutoff = datetime.now(UTC) - timedelta(days=_COST_WINDOW_DAYS)
        month_start = normalize_month(datetime.now(UTC).date())
        month_end_exclusive = add_months(month_start, 1)

        review_agg = (
            select(
                Review.tenant_id.label("tenant_id"),
                func.count().label("review_count"),
            )
            .where(Review.deleted_at.is_(None))
            .group_by(Review.tenant_id)
            .subquery()
        )
        upload_agg = (
            select(
                AnalyzeBatchJob.tenant_id.label("tenant_id"),
                func.max(AnalyzeBatchJob.created_at).label("last_upload_at"),
            )
            .group_by(AnalyzeBatchJob.tenant_id)
            .subquery()
        )
        cost_agg = (
            select(
                LlmCallAudit.tenant_id.label("tenant_id"),
                func.sum(LlmCallAudit.total_tokens).label("tokens_30d"),
                func.sum(LlmCallAudit.cost_usd).label("cost_30d_usd"),
            )
            .where(LlmCallAudit.created_at >= cost_cutoff)
            .group_by(LlmCallAudit.tenant_id)
            .subquery()
        )
        txn_agg = (
            select(
                TenantMonthlyMetric.tenant_id.label("tenant_id"),
                TenantMonthlyMetric.transaction_count.label("transaction_count"),
            )
            .where(TenantMonthlyMetric.period_month == month_start)
            .subquery()
        )
        # Katılım oranının payı: cari ayın yorum sayısı, quality_flag
        # damgalı satırlar hariç — engagement_service.monthly_review_counts
        # ile AYNI filtre (bkz. o fonksiyonun docstring'i). review_count
        # alanı (yukarıdaki review_agg) bilinçli olarak bunu YAPMAZ —
        # o alan "kurumda toplam kaç yorum var" hacim göstergesi, bu
        # ise yalnız katılım oranının girdisi.
        month_review_agg = (
            select(
                Review.tenant_id.label("tenant_id"),
                func.count().label("month_review_count"),
            )
            .where(Review.deleted_at.is_(None))
            .where(Review.quality_flag.is_(None))
            .where(Review.review_date >= month_start)
            .where(Review.review_date < month_end_exclusive)
            .group_by(Review.tenant_id)
            .subquery()
        )

        stmt = (
            select(
                Tenant,
                func.coalesce(review_agg.c.review_count, 0),
                upload_agg.c.last_upload_at,
                func.coalesce(cost_agg.c.tokens_30d, 0),
                cost_agg.c.cost_30d_usd,
                txn_agg.c.transaction_count,
                func.coalesce(month_review_agg.c.month_review_count, 0),
            )
            .outerjoin(review_agg, review_agg.c.tenant_id == Tenant.id)
            .outerjoin(upload_agg, upload_agg.c.tenant_id == Tenant.id)
            .outerjoin(cost_agg, cost_agg.c.tenant_id == Tenant.id)
            .outerjoin(txn_agg, txn_agg.c.tenant_id == Tenant.id)
            .outerjoin(month_review_agg, month_review_agg.c.tenant_id == Tenant.id)
            .order_by(Tenant.created_at.desc())
        )
        if not include_deleted:
            stmt = stmt.where(Tenant.deleted_at.is_(None))

        rows = (await self._session.execute(stmt)).all()
        bands_by_tenant = await self._bulk_bands([r[0].id for r in rows])

        out: list[TenantListRow] = []
        for (
            tenant,
            review_count,
            last_upload_at,
            tokens_30d,
            cost_30d_usd,
            transaction_count,
            month_review_count,
        ) in rows:
            pct = compute_engagement_pct(
                int(month_review_count or 0),
                int(transaction_count) if transaction_count is not None else None,
            )
            bands = bands_by_tenant.get(tenant.id) or [dict(b) for b in DEFAULT_BANDS]
            _, band_label = resolve_band(pct, bands)
            out.append(
                TenantListRow(
                    tenant=tenant,
                    review_count=int(review_count or 0),
                    last_upload_at=last_upload_at,
                    tokens_30d=int(tokens_30d or 0),
                    cost_30d_usd=cost_30d_usd,
                    engagement_band=band_label,
                )
            )
        return out

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
