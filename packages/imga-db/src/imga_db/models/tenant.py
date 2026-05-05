"""Tenant model + supporting enums."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import SoftDeleteMixin, TimestampMixin

# NOTE: A ``category_overrides`` JSON column existed on this table from
# migration 0001 as a 7.4 placeholder. It was dropped in migration 0005
# in favour of normalized ``categories`` + ``tenant_categories`` tables.


class TenantPlanTier(StrEnum):
    TRIAL = "trial"
    STARTER = "starter"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class AutomationMode(StrEnum):
    """Per-tenant ticket auto-creation policy."""

    MANUAL = "manual"  # No auto-tickets, only suggestions surfaced in UI
    SEMI_AUTO = "semi_auto"  # Auto-create when confidence > 0.7 + sentiment < -0.5
    FULL_AUTO = "full_auto"  # Every NEGATIF complaint becomes a ticket


class SlaWebhookDispatchMode(StrEnum):
    """Per-tenant SLA webhook dispatch policy (Sprint 9.0).

    AUTOMATIC: matching SLA rule fires httpx.post immediately (8.3.10
    behaviour, default).
    MANUAL: SLA engine queues a row in pending_webhook_events; an
    operator approves or dismisses it from /pending-webhooks.
    """

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class Tenant(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    plan_tier: Mapped[TenantPlanTier] = mapped_column(
        String(32),
        default=TenantPlanTier.TRIAL,
        nullable=False,
    )
    automation_mode: Mapped[AutomationMode] = mapped_column(
        String(32),
        default=AutomationMode.SEMI_AUTO,
        nullable=False,
    )

    # Free-form misc settings (notification prefs, branding, etc).
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # --- Sprint 7.5 ticket-lifecycle timer windows ----------------------
    # Dedicated INTEGER columns (not JSON) so per-tenant timer queries
    # can be indexed and joined cheaply. Defaults are the platform-wide
    # recommendations from the 7.5 design review.
    auto_close_resolved_days: Mapped[int] = mapped_column(
        Integer, default=7, nullable=False
    )
    auto_close_pending_days: Mapped[int] = mapped_column(
        Integer, default=14, nullable=False
    )
    resolved_regression_window_days: Mapped[int] = mapped_column(
        Integer, default=7, nullable=False
    )
    ticket_reopen_window_days: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )

    # --- Sprint 8.3.6 — tenant context for SWOT/OKR prompt injection ----
    # Nullable: existing tenants come up empty until /settings/profile
    # backfills them. industry is a hybrid enum — when ``other`` the
    # ``industry_other_text`` column carries the free-form label.
    # company_size is a coarse enum (solo / small / medium / large /
    # enterprise) for prompt segmentation.
    industry: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    industry_other_text: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    company_size: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    business_description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    # --- Sprint 9.0 — SLA webhook dispatch mode ------------------------
    # Default 'automatic' so existing tenants keep firing webhooks
    # synchronously. Migration 0022 adds the column with this default;
    # the engine reads it via TenantConfigService.
    sla_webhook_dispatch_mode: Mapped[SlaWebhookDispatchMode] = mapped_column(
        String(16),
        default=SlaWebhookDispatchMode.AUTOMATIC,
        nullable=False,
    )
