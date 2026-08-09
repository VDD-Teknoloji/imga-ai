"""TenantLlmCredential model — encrypted per-tenant LLM API key.

Sprint 8.3.6 / Alt-Faz 8.3.6.1.F. One row per (tenant, provider,
priority) — ``priority=0`` is the primary key the GeminiKeyRotator
tries first; 1+ are fallback in rotation order. ``encrypted_value``
holds the Fernet-token bytes from
``imga_core.security.encryption.encrypt()`` (never plaintext).

The rotator marks a key with ``last_failed_at`` on a permanent error
(invalid key, deactivated account) and skips it on the next pass; a
transient rate-limit doesn't update the timestamp, just bumps to the
next priority.

RLS+FORCE on tenant_id (migration 0019) — same convention every
tenant-scoped table since 0001.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TenantLlmCredential(Base):
    """Encrypted LLM credential row.

    ``provider`` is open-string today (only ``"gemini"`` exists in
    Sprint 8.3.6) but the column shape supports ``"openai"`` /
    ``"anthropic"`` without a schema change.
    """

    __tablename__ = "tenant_llm_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "priority",
            name="uq_tenant_provider_priority",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    # 0037 — kurum başına model seçimi (örn. "openai/gpt-5-mini").
    # NULL → sağlayıcının kod içi varsayılanı.
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
