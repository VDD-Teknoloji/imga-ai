"""Invitation model for the admin-invite-only signup flow.

The plaintext token never reaches the DB: the API hashes it (SHA-256)
before INSERT and on accept. The 7-day TTL is enforced in the service
layer, not via DB constraint, so an admin can extend by issuing a fresh
invitation rather than mutating expires_at.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import TimestampMixin
from imga_db.models.user import UserTenantRole


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[UserTenantRole] = mapped_column(String(32), nullable=False)

    # SHA-256 hex digest of the plaintext token sent in the email link.
    # Unique so the same token cannot be issued twice.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    invited_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
