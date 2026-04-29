"""Shared SQLAlchemy 2.0 mixins.

TenantOwnedMixin is what flags a table for the RLS policy applied in the
initial Alembic migration; any model that inherits it must have the RLS
SELECT/INSERT/UPDATE/DELETE policies enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

if TYPE_CHECKING:
    pass


class TimestampMixin:
    """Adds created_at + updated_at columns managed by the DB server."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds a nullable deleted_at column. Application code is responsible
    for filtering soft-deleted rows; Postgres RLS does not handle that here.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )


class TenantOwnedMixin:
    """Marks a table as tenant-scoped.

    Every table that inherits this is subject to the RLS policy that requires
    `tenant_id = current_setting('app.current_tenant_id')::uuid`. The
    initial Alembic migration enables RLS on all such tables.
    """

    @declared_attr
    @classmethod
    def tenant_id(cls) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
