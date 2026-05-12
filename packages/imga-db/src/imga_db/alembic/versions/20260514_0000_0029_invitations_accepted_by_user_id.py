"""Sprint 9.5 A2 — invitations.accepted_by_user_id audit FK

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-14 00:00:00

Production hardening for the invitation-accept flow. Two halves:

  1. Schema: ``invitations.accepted_by_user_id`` — nullable FK to
     users(id). Carries the id of the user who actually claimed the
     invitation (distinct from ``invited_by``, which is the inviter,
     and from ``email``, which is the address the invite was issued
     to — they CAN differ if a different account email shares an
     inbox alias).

  2. Behavior (lives in the service layer, see
     InvitationService._claim refactor): for the existing-user
     accept path the email-match check runs BEFORE the atomic
     UPDATE, so a wrong-email caller who happens to know their own
     password can't burn an invitation that wasn't issued to them
     — pre-9.5 the token was consumed first, mismatch raised after,
     and the row's accepted_at was already set on rollback-isolated
     transactions.

Backfill — for rows that already have ``accepted_at`` set, attempt
to recover ``accepted_by_user_id`` by joining invitations.email to
users.email. users.email is globally unique so this is single-valued.
If no matching user exists the column stays NULL — historical
analytics that need the answer can re-derive from audit_logs
(``invitation.accept`` rows carry actor_user_id).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column(
            "accepted_by_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_invitations_accepted_by_user_id_users",
        source_table="invitations",
        referent_table="users",
        local_cols=["accepted_by_user_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    # Backfill — best-effort match by email. NULL when the inviting
    # email doesn't correspond to any current user row (the invited
    # user might have been hard-deleted, or the invitation was claimed
    # via the legacy auto-pick path that mints a new user; in both
    # cases the audit_logs trail remains the source of truth).
    op.execute(
        """
        UPDATE invitations i
        SET accepted_by_user_id = u.id
        FROM users u
        WHERE i.accepted_at IS NOT NULL
          AND i.accepted_by_user_id IS NULL
          AND lower(u.email) = lower(i.email)
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_invitations_accepted_by_user_id_users",
        "invitations",
        type_="foreignkey",
    )
    op.drop_column("invitations", "accepted_by_user_id")
