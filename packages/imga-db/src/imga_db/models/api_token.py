"""ApiTokenRecord + AdminTokenRecord — İmga v1 partner API auth token'ları.

Migration 0032. ``api_tokens`` kiracı-scoped (RLS+FORCE tenant_isolation);
``admin_tokens`` ops (tenant YOK, deny-all RLS — §8.6). ``token_hash`` =
HMAC-SHA256(pepper) hex; plaintext ASLA saklanmaz (Invitation.token_hash
deseni — imga_api.security.api_tokens). Tasarım:
docs/analysis/2026-07-01-apitokenrecord-migration-design.md
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class ApiTokenRecord(Base):
    """Kiracı-başına opak API token (scope=tenant). RLS+FORCE.

    Önek Stripe-style (``imga_live_`` / ``imga_stg_``); gövde 32-byte random.
    ``token_hash`` HMAC-SHA256 hex — auth sıcak yolu tek indeksli lookup.
    """

    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("scope = 'tenant'", name="ck_api_tokens_scope"),
        Index("ix_api_tokens_token_hash", "token_hash", unique=True),
        Index("ix_api_tokens_tenant_id", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="tenant")
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    # Mint eden kullanıcı (ops console). Kullanıcı silinince NULL — token
    # yaşamaya devam eder; offboard revoke'u app katmanında (tasarım §6).
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # ölümsüz token YOK: NOT NULL; mint ≤1 yıl.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AdminTokenRecord(Base):
    """VDD Ops token (scope=ops, §8.6). tenant_id YOK.

    Önek ``imga_ops_live_`` / ``imga_ops_stg_``. Deny-all RLS: imga_app sıfır
    satır görür, yalnız imga_admin (BYPASSRLS) erişir. ``/v1/admin/*`` uçlarını
    yetkilendirir; tenant token'ı buraya erişemez.
    """

    __tablename__ = "admin_tokens"
    __table_args__ = (
        CheckConstraint("scope = 'ops'", name="ck_admin_tokens_scope"),
        Index("ix_admin_tokens_token_hash", "token_hash", unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    token_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="ops")
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
