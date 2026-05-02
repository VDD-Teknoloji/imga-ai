"""Review model — analyzed-text archive + auto-ticket bridge log.

Sprint 7.5.5 / Alt-Faz 3. Every call to ``POST /tenants/me/analyze``
writes one row here. The row captures the analyzer output AND the
bridge decision (``create`` or one of the four ``skipped_*`` reasons),
so the historical record explains *why* a complaint did or didn't
become a ticket.

The ``text_hash`` column is a sha256 hex over
``normalize_turkish(text).strip()`` (see ``imga_core.text_utils``).
Identical user submissions collapse to identical hashes; a 24-hour
window on this hash drives the dedup branch.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CHAR, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import SoftDeleteMixin, TimestampMixin


class ReviewDecision(StrEnum):
    """Outcome of the bridge for a single analyzed review.

    Order = evaluation precedence in ReviewService:

      1. ``skipped_belirsiz`` — primary category is "belirsiz" (unknown);
         no mode auto-creates from this.
      2. ``skipped_mode``     — tenant is in MANUAL automation_mode.
      3. ``skipped_threshold``— SEMI_AUTO confidence/sentiment under
         the threshold, or FULL_AUTO sentiment >= 0.
      4. ``skipped_dedup``    — same text_hash already produced a
         ticket within the last 24h; this row points at that ticket.
      5. ``create``           — all guards passed; new ticket minted.
    """

    CREATE = "create"
    SKIPPED_BELIRSIZ = "skipped_belirsiz"
    SKIPPED_MODE = "skipped_mode"
    SKIPPED_THRESHOLD = "skipped_threshold"
    SKIPPED_DEDUP = "skipped_dedup"


class Review(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "reviews"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(Text(), nullable=False)
    # sha256 hex over normalize_turkish(text).strip(). Fixed CHAR(64);
    # the DB CHECK constraint enforces length so a malformed value never
    # lands.
    text_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    sentiment_label: Mapped[str] = mapped_column(String(8), nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Float(), nullable=False)
    primary_category: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_confidence: Mapped[float] = mapped_column(Float(), nullable=False)

    # Snapshot of automation_mode at decision time. Tenant config can
    # flip between calls; this preserves the value that produced the
    # decision below, so audits stay self-explanatory.
    automation_mode: Mapped[str] = mapped_column(String(16), nullable=False)

    decision: Mapped[ReviewDecision] = mapped_column(String(32), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # Set on `create` (newly minted ticket) AND `skipped_dedup` (pointer
    # to the existing ticket). Other branches leave NULL.
    ticket_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Sprint 8.3.1 batch upload back-reference. NULL for /tenants/me/analyze
    # rows; populated for rows the batch worker writes. ``ix_reviews_batch``
    # is a partial index so the dominant non-batch case stays cheap.
    batch_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("analyze_batch_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
