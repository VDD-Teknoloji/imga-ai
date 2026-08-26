"""LLMCallAudit — per-call audit row for governance.

Sprint 9.3 A. Every LLM call (classification, briefing, strategic
report, action extraction) writes one row capturing the prompt
template + version, model meta, token usage, duration, success /
error metadata, and the request_id from Sprint 9.1 C so the
operator can correlate a UI failure to the underlying provider
call.

The ``LLMCallAuditor`` context manager in
``imga_core.llm.audit`` is the canonical writer; routes / services
that go through it never touch this row directly. RLS+FORCE on
``tenant_id`` per the 0006 / 0019 / 0021 / 0024 / 0026 convention.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class LlmCallAudit(Base):
    __tablename__ = "llm_call_audit"
    __table_args__ = (
        CheckConstraint(
            "call_type IN ('classification', 'briefing', "
            "'strategic_report', 'action_extraction', 'okr', "
            "'root_cause', 'quality_report', 'onboarding_suggest', "
            "'twitter_keywords', 'twitter_relevance')",
            name="ck_llm_call_audit_call_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    call_type: Mapped[str] = mapped_column(Text(), nullable=False)
    related_entity_type: Mapped[str | None] = mapped_column(Text(), nullable=True)
    related_entity_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    prompt_template_key: Mapped[str | None] = mapped_column(Text(), nullable=True)
    prompt_template_version: Mapped[str | None] = mapped_column(Text(), nullable=True)
    prompt_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    model_name: Mapped[str] = mapped_column(Text(), nullable=False)
    model_provider: Mapped[str] = mapped_column(Text(), nullable=False)
    model_temperature: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    model_max_tokens: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # Sprint 9.4.2 hotfix — Migration 0027 ships ``total_tokens`` as a
    # PostgreSQL ``GENERATED ALWAYS AS ... STORED`` column. The ORM
    # has to mirror that with ``Computed(..., persisted=True)`` so
    # SQLAlchemy's INSERT path excludes the column instead of sending
    # ``total_tokens=NULL`` (which Postgres rejects with
    # ``GeneratedAlwaysError`` against a generated-always column).
    # Pre-fix every audit insert hit the savepoint rollback path
    # from Sprint 9.4 F and the audit table stayed empty in prod.
    total_tokens: Mapped[int | None] = mapped_column(
        Integer(),
        Computed(
            "COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)",
            persisted=True,
        ),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    # 2026-08-20 (migration 0045, B6) — çağrı başına tahmini USD
    # maliyeti. ``imga_api.services.llm_pricing.cost_usd`` statik
    # fiyat tablosundan hesaplanır (provider+model bilinmiyorsa ya da
    # fiyatı elle girilmemişse None). NULL = "bilinmiyor", 0 DEĞİL —
    # backfill yok, eski satırlar kalıcı olarak NULL.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    error_type: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
