"""Trial analysis result row — public /public/trial/analyze backing store.

Sprint 9.7. The imga.ai marketing site proxies email-verified
visitors into the SaaS for a one-shot ≤100-row analysis demo; the
result lives here for 24h (idempotency window — a duplicate call
for the same email returns the cached payload) and then GC sweeps
it.

KVKK posture: we keep ONLY aggregated counts + a small set of
sampled review excerpts in the result payload. No row-level review
text persists outside the 24h window. The trial endpoint does NOT
write to the ``reviews`` table at all.

Singleton tenant: every row carries
``tenant_id = TRIAL_TENANT_ID = 00000000-0000-0000-0000-000000000777``
— matches the seed row added by migration 0030. RLS+FORCE is on so
a session without ``app.current_tenant_id`` set to that uuid sees
nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base


class TrialAnalysis(Base):
    __tablename__ = "trial_analyses"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Lookup key for idempotency. Lowercased + stripped at insert by
    # the service layer; the partial UNIQUE index in migration 0030
    # enforces one row per email at the DB level too.
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # Correlation id surfaced to the marketing site so the trial_runs
    # row on that side can reference our row without a tenant_id
    # boundary cross. Defaults to a fresh uuid; tests can override.
    request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, default=uuid4
    )

    file_name: Mapped[str | None] = mapped_column(Text(), nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer(), nullable=False)

    # Aggregated result payload. Shape pinned in
    # trial_analysis_service._build_response (and mirrored on the
    # marketing site so its `TrialResults` type matches one-to-one).
    sentiment_distribution: Mapped[dict[str, int]] = mapped_column(
        JSONB(), nullable=False, default=dict
    )
    top_categories: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    sample_reviews: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(), nullable=False, default=list
    )
    nps_estimate: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(
        Integer(), nullable=True
    )

    # Marketing site's trial_users.id — audit only, FK not enforced
    # (the row lives in a separate DB).
    trial_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Lazy GC: the service deletes rows with expires_at < now() at
    # the start of every new request, so no scheduled worker is
    # needed. Set to created_at + 24h at insert.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
