"""TicketComment model — internal notes + customer replies + archive.

Sprint 7.5.5 / Alt-Faz 4. Comments live alongside the
``ticket_state_transitions`` timeline; the ``GET /tickets/{id}/timeline``
endpoint merges both into a single chronological event stream.

Two ``kind`` values:

  * ``internal_note``  — visible to the tenant team only. Any role.
  * ``customer_reply`` — outbound message text. ANALYST + TENANT_ADMIN
                         only; forbidden when the ticket is CLOSED or
                         CANCELLED (CommentService enforces).

Archive (soft delete) is the only retract path — hard delete is
intentionally absent so the timeline can't be silently rewritten.
``deleted_at`` doubles as the archive timestamp; ``archived_by_user_id``
records who pressed the button.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from imga_db.base import Base
from imga_db.models.mixins import SoftDeleteMixin, TimestampMixin


class TicketCommentKind(StrEnum):
    INTERNAL_NOTE = "internal_note"
    CUSTOMER_REPLY = "customer_reply"


class TicketComment(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ticket_comments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL on user delete: the comment survives as evidence even
    # after the author leaves the team. UI shows "Unknown analyst".
    author_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    body: Mapped[str] = mapped_column(Text(), nullable=False)
    kind: Mapped[TicketCommentKind] = mapped_column(String(16), nullable=False)

    # Audit pointer for the archive event. NULL on live comments.
    archived_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    @property
    def is_archived(self) -> bool:
        """Convenience wrapper — DB has no separate flag, ``deleted_at``
        is NOT NULL exactly when the comment is archived."""
        return self.deleted_at is not None

    @property
    def archived_at(self) -> datetime | None:
        """Alias for ``deleted_at``. Reads better in audit / UI code
        where 'archived_at' is the more honest name."""
        return self.deleted_at
