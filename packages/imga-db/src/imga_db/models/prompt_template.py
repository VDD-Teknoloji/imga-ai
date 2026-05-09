"""PromptTemplate model — system-level + tenant-override prompt registry.

Sprint 8.3.6 / Alt-Faz 8.3.6.1.F shipped this as global only (one
row per ``template_key``). Sprint 9.3 D adds the per-tenant
override hierarchy:

  * ``tenant_id IS NULL`` — global default; every tenant reads it.
  * ``tenant_id`` set + ``is_default = TRUE`` — tenant override that
    replaces the global default for that tenant only.
  * ``version`` — historical track; the default version is the
    current one, older versions stay around for audit + rollback.

The ``PromptResolver`` in ``imga_core.llm.prompt_resolver`` walks
this fallback chain so call sites stay unchanged: they ask for a
``template_key`` and get the highest-priority match the registry
provides.

RLS+FORCE: tenant overrides isolated, global rows readable by
everyone. The composite UNIQUE on (template_key, version,
tenant_id) permits one row per slot; a partial unique index on
(template_key, COALESCE(tenant_id::text, '')) WHERE is_default = TRUE
enforces "one default per template_key per tenant (or per global)".

``is_active`` predates 9.3 and is preserved (existing service code
reads it). ``is_default`` is the 9.3 "current version" flag — they
overlap but aren't identical: an admin can disable a row entirely
(``is_active = FALSE``) without it being the default.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "template_key",
            "version",
            "tenant_id",
            name="uq_prompt_templates_key_version_tenant",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Sprint 9.3 D — version + tenant_id form the composite unique.
    version: Mapped[str] = mapped_column(Text(), nullable=False, default="v1")
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )

    system_prompt: Mapped[str] = mapped_column(Text(), nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text(), nullable=False)
    response_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB(), nullable=False
    )

    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature: Mapped[float] = mapped_column(Float(), nullable=False, default=0.2)
    top_p: Mapped[float] = mapped_column(Float(), nullable=False, default=0.9)
    max_output_tokens: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=8192
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    # Sprint 9.3 D — default version flag. ``is_default = TRUE`` plus
    # ``is_active = TRUE`` means "this is what fires when a service
    # asks for the template". The partial unique index in Migration
    # 0027 enforces one default per (template_key, tenant_id-or-global).
    is_default: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    required_variables: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, default=list
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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
