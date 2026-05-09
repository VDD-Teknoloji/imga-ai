"""Sprint 9.1 A — action item lifecycle service.

The route layer used to mutate ``ActionItem`` rows directly. Sprint
9.1 A introduces a journalled lifecycle (every state change writes
an ``ActionItemEvent`` row) and a soft-delete contract (DELETE flips
``archived_at`` instead of removing the row), so the route layer now
delegates to this service for everything except the unauthenticated
``extract-from-report`` bulk insert path (which still goes through
the route directly because its event semantics are clearer there —
one ``created`` event per row written from the same transaction).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from imga_db.models import ActionItem, ActionItemEvent
from sqlalchemy.ext.asyncio import AsyncSession


class ActionItemError(Exception):
    """Service-layer failure that should map to a 4xx — the route
    handler converts this into HTTPException; bare exceptions become
    500 via the generic 5xx handler."""


class ActionItemNotFound(ActionItemError):
    """The id doesn't exist in the active tenant scope."""


class ActionItemAlreadyArchived(ActionItemError):
    """archive() called on an already-archived row."""


class ActionItemNotArchived(ActionItemError):
    """restore() called on a non-archived row."""


# Event types — Migration 0025's CHECK constraint enforces this set.
EVENT_CREATED = "created"
EVENT_UPDATED = "updated"
EVENT_ARCHIVED = "archived"
EVENT_UNARCHIVED = "unarchived"
EVENT_STATUS_CHANGED = "status_changed"
EVENT_PRIORITY_CHANGED = "priority_changed"
EVENT_ASSIGNED = "assigned"
EVENT_UNASSIGNED = "unassigned"


# Actor types — service callers are humans by default; the LLM
# extraction path (``action_extraction_service``) and the briefing
# pipeline pass ``llm_extraction`` / ``briefing_pipeline`` so the
# timeline UI can render them differently.
ACTOR_USER = "user"
ACTOR_SYSTEM = "system"
ACTOR_LLM_EXTRACTION = "llm_extraction"
ACTOR_BRIEFING_PIPELINE = "briefing_pipeline"


_TRACKED_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "rationale",
    "priority",
    "estimated_impact",
    "status",
    "assignee_user_id",
    "due_date",
)


class ActionItemService:
    """All mutations route through here so the audit trail is the
    single source of truth for "who did what when". The service does
    NOT manage transactions — callers wrap each public method inside
    their own ``async with session.begin():`` (the FastAPI route
    layer does this for the request-scoped app session)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update(
        self,
        *,
        item_id: UUID,
        tenant_id: UUID,
        updates: dict[str, Any],
        actor_user_id: UUID | None,
        actor_type: str = ACTOR_USER,
    ) -> ActionItem:
        """Apply field updates and emit one ``updated`` event plus
        targeted ``status_changed`` / ``priority_changed`` /
        ``assigned`` / ``unassigned`` events for the fields that
        actually changed. The targeted events make the timeline UI
        readable — a single row that says "status: open → done"
        beats five-key diff JSON.
        """
        row = await self._fetch(item_id, tenant_id)

        before: dict[str, Any] = {
            field: getattr(row, field) for field in _TRACKED_FIELDS
        }
        diff: dict[str, Any] = {}
        for field, new_value in updates.items():
            if field not in _TRACKED_FIELDS:
                continue
            old_value = before[field]
            if old_value == new_value:
                continue
            setattr(row, field, new_value)
            diff[field] = {"from": _to_jsonable(old_value), "to": _to_jsonable(new_value)}

        # Auto-stamp completed_at when transitioning to ``done``.
        new_status = updates.get("status")
        if new_status == "done" and row.completed_at is None:
            row.completed_at = datetime.now(UTC)
        elif new_status is not None and new_status != "done":
            row.completed_at = None

        await self._session.flush()

        if not diff:
            return row

        # The umbrella ``updated`` event captures the full diff so a
        # consumer that just wants "what changed at this moment" can
        # render the JSON; the targeted events surface the most-
        # asked-about transitions as their own rows.
        await self._emit(
            row,
            event_type=EVENT_UPDATED,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            payload={"diff": diff},
        )
        if "status" in diff:
            await self._emit(
                row,
                event_type=EVENT_STATUS_CHANGED,
                actor_user_id=actor_user_id,
                actor_type=actor_type,
                payload=diff["status"],
            )
        if "priority" in diff:
            await self._emit(
                row,
                event_type=EVENT_PRIORITY_CHANGED,
                actor_user_id=actor_user_id,
                actor_type=actor_type,
                payload=diff["priority"],
            )
        if "assignee_user_id" in diff:
            ev = (
                EVENT_UNASSIGNED
                if diff["assignee_user_id"]["to"] is None
                else EVENT_ASSIGNED
            )
            await self._emit(
                row,
                event_type=ev,
                actor_user_id=actor_user_id,
                actor_type=actor_type,
                payload=diff["assignee_user_id"],
            )
        return row

    async def archive(
        self,
        *,
        item_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
    ) -> ActionItem:
        """Soft-delete: stamp ``archived_at`` + ``archived_by`` and
        emit one ``archived`` event. Idempotent only on the no-op
        sense — archiving an already-archived row raises
        ``ActionItemAlreadyArchived`` so the operator sees an explicit
        409 rather than a silent no-op."""
        row = await self._fetch(item_id, tenant_id)
        if row.archived_at is not None:
            raise ActionItemAlreadyArchived(
                f"action_item {item_id} is already archived"
            )
        row.archived_at = datetime.now(UTC)
        row.archived_by = actor_user_id
        await self._session.flush()
        await self._emit(
            row,
            event_type=EVENT_ARCHIVED,
            actor_user_id=actor_user_id,
            actor_type=ACTOR_USER,
            payload={
                "archived_at": row.archived_at.isoformat(),
            },
        )
        return row

    async def restore(
        self,
        *,
        item_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID | None,
    ) -> ActionItem:
        """Reverse of archive — clear ``archived_at`` / ``archived_by``
        and emit ``unarchived``. 409 if the row isn't archived."""
        row = await self._fetch(item_id, tenant_id)
        if row.archived_at is None:
            raise ActionItemNotArchived(
                f"action_item {item_id} is not archived"
            )
        previous_archived_at = row.archived_at
        row.archived_at = None
        row.archived_by = None
        await self._session.flush()
        await self._emit(
            row,
            event_type=EVENT_UNARCHIVED,
            actor_user_id=actor_user_id,
            actor_type=ACTOR_USER,
            payload={
                "previous_archived_at": previous_archived_at.isoformat(),
            },
        )
        return row

    async def emit_created(
        self,
        *,
        row: ActionItem,
        actor_user_id: UUID | None,
        actor_type: str = ACTOR_USER,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Convenience for the create + extract paths — the route
        layer instantiates the row inside its own transaction (so
        the FK constraint sees a real id) and calls this to journal
        the creation."""
        await self._emit(
            row,
            event_type=EVENT_CREATED,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            payload=payload or {},
        )

    # ---- internals ----------------------------------------------------

    async def _fetch(self, item_id: UUID, tenant_id: UUID) -> ActionItem:
        row = await self._session.get(ActionItem, item_id)
        if row is None or row.tenant_id != tenant_id:
            raise ActionItemNotFound(
                f"action_item {item_id} not found in tenant {tenant_id}"
            )
        return row

    async def _emit(
        self,
        row: ActionItem,
        *,
        event_type: str,
        actor_user_id: UUID | None,
        actor_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = ActionItemEvent(
            tenant_id=row.tenant_id,
            action_item_id=row.id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            payload=payload,
        )
        self._session.add(event)
        await self._session.flush()


def _to_jsonable(value: Any) -> Any:
    """JSONB encodes UUIDs / datetimes via str(); we serialise here
    so the diff payload reads cleanly out of psql + survives a
    ``json.loads`` on the timeline endpoint without surprises."""
    if value is None:
        return None
    if isinstance(value, UUID | datetime):
        return str(value)
    return value


__all__ = [
    "ACTOR_BRIEFING_PIPELINE",
    "ACTOR_LLM_EXTRACTION",
    "ACTOR_SYSTEM",
    "ACTOR_USER",
    "ActionItemAlreadyArchived",
    "ActionItemError",
    "ActionItemNotArchived",
    "ActionItemNotFound",
    "ActionItemService",
    "EVENT_ARCHIVED",
    "EVENT_ASSIGNED",
    "EVENT_CREATED",
    "EVENT_PRIORITY_CHANGED",
    "EVENT_STATUS_CHANGED",
    "EVENT_UNARCHIVED",
    "EVENT_UNASSIGNED",
    "EVENT_UPDATED",
]
