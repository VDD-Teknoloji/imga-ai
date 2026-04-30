"""ticket_comments — internal notes + customer replies + archive

Revision ID: 0009
Revises: 0008
Create Date: 2026-01-09 00:00:00

Sprint 7.5.5 / Alt-Faz 4: comments alongside the ticket lifecycle.
The Sprint 7.5 design review locked in two comment kinds:

  * ``internal_note``   — visible to tenant team only. Any role
                          (VIEWER / ANALYST / TENANT_ADMIN) can write.
  * ``customer_reply``  — text sent (now or later) to the customer.
                          ANALYST + TENANT_ADMIN only; VIEWER cannot
                          write these (they are read-only members).

Comments are state-orthogonal — they can be added at any ticket
state (OPEN through CANCELLED) — with one exception: ``customer_reply``
is forbidden once the ticket is CLOSED or CANCELLED, since outbound
customer messaging on a terminal ticket is a UX foot-gun. The DB
does not enforce that biconditional (state lives on tickets, not
comments); CommentService raises a 403 for that case.

Retract mechanism: archive (soft delete), NOT hard delete. The
SoftDeleteMixin's ``deleted_at`` column doubles as the archive flag.
Authors can archive their own comment; TENANT_ADMIN can archive any.
Archived rows still surface in the timeline endpoint with
``is_archived=true`` so the historical record is intact — destroying
context would let a misbehaving analyst rewrite history.

``archived_by_user_id`` is the dedicated audit pointer; ``deleted_at``
records WHEN, this column records WHO. Both are NULL for live rows.

RLS+FORCE on ``tenant_id`` is applied with the same policy convention
as the rest of the schema. Indexes:

  * (tenant_id, ticket_id, created_at) — backs the per-ticket
    timeline render. Created_at ascending so the merged timeline
    (transitions + comments) sorts in chronological order.
  * (tenant_id, author_user_id) — "my comments" lookup; small
    enough that we keep it without a partial filter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_comments",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # author_user_id is SET NULL on user delete so the comment
        # survives as anonymous-attribution evidence (the team timeline
        # remains intact even after staff churn).
        sa.Column(
            "author_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        # Audit pointer for the archive event. NULL on live comments.
        sa.Column(
            "archived_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # SoftDeleteMixin parity: deleted_at NOT NULL signals archived.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('internal_note','customer_reply')",
            name="ck_ticket_comments_kind",
        ),
        sa.CheckConstraint(
            "char_length(body) >= 1",
            name="ck_ticket_comments_body_nonempty",
        ),
        # Defence in depth — service should refuse before the DB sees
        # the row, but stop a runaway author from saving 10MB blobs.
        sa.CheckConstraint(
            "char_length(body) <= 8000",
            name="ck_ticket_comments_body_length",
        ),
    )
    op.create_index(
        "ix_ticket_comments_tenant_ticket_created",
        "ticket_comments",
        ["tenant_id", "ticket_id", "created_at"],
    )
    op.create_index(
        "ix_ticket_comments_tenant_author",
        "ticket_comments",
        ["tenant_id", "author_user_id"],
    )
    op.create_index(
        "ix_ticket_comments_deleted_at",
        "ticket_comments",
        ["deleted_at"],
    )

    op.execute("ALTER TABLE ticket_comments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ticket_comments FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ticket_comments
            FOR ALL
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ticket_comments")
    op.execute("ALTER TABLE ticket_comments DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_ticket_comments_deleted_at", table_name="ticket_comments")
    op.drop_index("ix_ticket_comments_tenant_author", table_name="ticket_comments")
    op.drop_index(
        "ix_ticket_comments_tenant_ticket_created", table_name="ticket_comments"
    )
    op.drop_table("ticket_comments")
