"""Refresh token rotation chain detection records.

Each refresh token issued to a client is persisted as one row. Rotation
chains share a `family_id`; the `parent_jti` link lets us detect token
reuse — a hallmark of compromise — and revoke the entire family.

Lifecycle states (queried, not stored as enum):
  - active:   used_at IS NULL AND revoked_at IS NULL AND expires_at > now()
  - rotated:  used_at IS NOT NULL                  (one-shot, child issued)
  - revoked:  revoked_at IS NOT NULL               (logout / chain compromise)
  - expired:  expires_at <= now()                  (cleanup target)
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class RefreshTokenRecord(Base):
    """One row per refresh token ever issued (active, rotated, revoked)."""

    __tablename__ = "refresh_token_records"

    jti: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # All tokens in a rotation chain share family_id; logout / compromise
    # revokes by family.
    family_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    parent_jti: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Tenant context bound to the rotation chain. Refresh keeps the
    # access-token claims stable across rotations — without these the
    # 15-min refresh would silently drop active_tenant_id and break
    # tenant-scoped endpoints. /switch-tenant opens a fresh family with
    # different values, so storing per-record (not per-family) is fine.
    active_tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    active_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
