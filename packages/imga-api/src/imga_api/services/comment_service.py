"""CommentService — internal notes + customer replies + archive.

Sprint 7.5.5 / Alt-Faz 4. Lives on the imga_app session (RLS-bound).
Caller binds the active tenant via ``bind_tenant`` inside its own
transaction; this service stays oblivious to the tenant beyond the
explicit ``tenant_id`` argument.

Role matrix (locked in during the Sprint 7.5 design review):

      role            | internal_note | customer_reply
      ----------------|---------------|----------------
      VIEWER          | write         | forbidden
      ANALYST         | write         | write
      TENANT_ADMIN    | write         | write

State guard: ``customer_reply`` is forbidden once the ticket is in
CLOSED or CANCELLED. Internal notes are state-orthogonal (allowed in
every state, including CLOSED/CANCELLED, so post-mortem notes are
possible).

Archive (soft delete) is the only retract path. Authors can archive
their own comment; TENANT_ADMIN can archive any. Once archived, the
row is preserved with ``deleted_at`` + ``archived_by_user_id`` set;
the timeline still surfaces it with ``is_archived=true`` so the
historical record stays intact.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from imga_db.models import (
    Ticket,
    TicketComment,
    TicketCommentKind,
    TicketState,
    UserTenantRole,
)
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService

# Body length matches the DB CHECK constraint. Validated server-side
# before insert so the client gets a clean 422 instead of a generic
# 500-style integrity error.
MAX_BODY_LENGTH = 8000


class CommentServiceError(Exception):
    """Base for CommentService failures."""


class CommentNotFoundError(CommentServiceError):
    """Comment doesn't exist in the active tenant or RLS hides it."""


class TicketNotFoundForCommentError(CommentServiceError):
    """The target ticket doesn't exist or is soft-deleted."""


class CommentForbiddenError(CommentServiceError):
    """Role / state matrix rejected the operation. Routes map to 403."""


class CommentService:
    def __init__(self, session: AsyncSession, audit: AuditService) -> None:
        self._session = session
        self._audit = audit

    # --- create ---------------------------------------------------------

    async def create(
        self,
        *,
        tenant_id: UUID,
        ticket_id: UUID,
        author_user_id: UUID,
        author_role: UserTenantRole,
        body: str,
        kind: TicketCommentKind,
    ) -> TicketComment:
        """Insert one comment after validating role + state guards.

        ``author_role`` is passed in (rather than re-derived from the
        DB) so super-admin callers without an active tenant role can
        be handled by the route layer — they pass TENANT_ADMIN to
        bypass the role matrix while still going through the state
        guard."""
        body_clean = body.strip()
        if not body_clean:
            raise CommentServiceError("comment body cannot be empty")
        if len(body_clean) > MAX_BODY_LENGTH:
            raise CommentServiceError(
                f"comment body exceeds {MAX_BODY_LENGTH}-char limit"
            )

        ticket = await self._session.get(Ticket, ticket_id)
        if ticket is None or ticket.deleted_at is not None:
            raise TicketNotFoundForCommentError(
                f"ticket {ticket_id} not found"
            )

        # --- role matrix ---
        if (
            kind == TicketCommentKind.CUSTOMER_REPLY
            and author_role == UserTenantRole.VIEWER
        ):
            raise CommentForbiddenError(
                "VIEWER role cannot post customer_reply comments"
            )

        # --- state guard for customer_reply ---
        if kind == TicketCommentKind.CUSTOMER_REPLY and ticket.state in (
            TicketState.CLOSED,
            TicketState.CANCELLED,
        ):
            raise CommentForbiddenError(
                f"customer_reply forbidden on {ticket.state} ticket; "
                "internal_note is still allowed"
            )

        comment = TicketComment(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            author_user_id=author_user_id,
            body=body_clean,
            kind=kind,
        )
        self._session.add(comment)
        await self._session.flush()

        await self._audit.log(
            action="comment.create",
            resource_type="comment",
            resource_id=comment.id,
            tenant_id=tenant_id,
            actor_user_id=author_user_id,
            details={
                "ticket_id": str(ticket_id),
                "kind": str(kind),
                "ticket_state": str(ticket.state),
            },
        )
        return comment

    # --- list -----------------------------------------------------------

    async def list_for_ticket(
        self,
        *,
        tenant_id: UUID,
        ticket_id: UUID,
        include_archived: bool = True,
    ) -> list[TicketComment]:
        """Return comments for a ticket in chronological order.

        Archived comments are surfaced by default (timeline needs them
        with is_archived=true); pass ``include_archived=False`` for a
        live-only list when the UI explicitly hides them."""
        # Tenant-scope predicate is redundant under RLS but acts as
        # defence in depth (and lets test code that runs on the admin
        # session still work without RLS engaged).
        stmt = (
            select(TicketComment)
            .where(TicketComment.tenant_id == tenant_id)
            .where(TicketComment.ticket_id == ticket_id)
            .order_by(asc(TicketComment.created_at))
        )
        if not include_archived:
            stmt = stmt.where(TicketComment.deleted_at.is_(None))
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows)

    # --- archive --------------------------------------------------------

    async def archive(
        self,
        *,
        comment_id: UUID,
        actor_user_id: UUID,
        actor_role: UserTenantRole,
        actor_is_super_admin: bool = False,
    ) -> TicketComment:
        """Soft-delete a comment.

        Authors can archive their own comment; TENANT_ADMIN (or
        super-admin) can archive any. Already-archived rows return a
        409 from the route, so we raise CommentForbiddenError with a
        distinct message the route maps to 409."""
        comment = await self._session.get(TicketComment, comment_id)
        if comment is None:
            raise CommentNotFoundError(f"comment {comment_id} not found")
        if comment.deleted_at is not None:
            raise CommentForbiddenError("comment is already archived")

        is_admin = (
            actor_role == UserTenantRole.TENANT_ADMIN or actor_is_super_admin
        )
        is_author = (
            comment.author_user_id is not None
            and comment.author_user_id == actor_user_id
        )
        if not (is_admin or is_author):
            raise CommentForbiddenError(
                "only the author or a tenant admin can archive this comment"
            )

        moment = datetime.now(UTC)
        comment.deleted_at = moment
        comment.archived_by_user_id = actor_user_id
        await self._session.flush()

        await self._audit.log(
            action="comment.archive",
            resource_type="comment",
            resource_id=comment.id,
            tenant_id=comment.tenant_id,
            actor_user_id=actor_user_id,
            details={
                "ticket_id": str(comment.ticket_id),
                "by_admin": is_admin,
                "self_archive": is_author,
            },
        )
        return comment


__all__ = [
    "MAX_BODY_LENGTH",
    "CommentForbiddenError",
    "CommentNotFoundError",
    "CommentService",
    "CommentServiceError",
    "TicketNotFoundForCommentError",
]
