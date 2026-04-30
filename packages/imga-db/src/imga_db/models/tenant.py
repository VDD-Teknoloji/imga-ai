"""Tenant model + supporting enums."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, String
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
