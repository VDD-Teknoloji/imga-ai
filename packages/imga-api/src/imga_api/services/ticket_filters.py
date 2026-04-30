"""TicketFilters — Pydantic model for the /tickets query surface.

Single source of truth for what's filterable + sortable. Lives in the
service layer (not routes/) so both ``TicketService.list_filtered`` and
``TicketService.stats`` can take the same shape and Sprint 8 batch
exporters can reuse it without dragging in FastAPI.

CSV semantics for multi-value parameters:

  ?state=open,in_progress  →  ["open", "in_progress"]
  ?state=open              →  ["open"]
  ?state=                  →  []   (no 422 — empty filter is valid)
  ?state                   →  []   (FastAPI defaults to None → [])

The ``mode="before"`` field validators run before Pydantic's own
strict enum validation, so the parsed list of strings flows through
the regular TicketState / TicketPriority parsers and rejects unknown
values with the standard 422.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from imga_db.models import TicketPriority, TicketState
from pydantic import BaseModel, ConfigDict, Field, field_validator

OrderBy = Literal["opened_at", "last_state_change_at", "priority"]
OrderDirection = Literal["asc", "desc"]
AssigneeFilter = Annotated[str | None, Field(default=None, max_length=64)]


def _split_csv(value: object) -> list[str] | object:
    """Validator helper. Strings split on comma, list/None pass through."""
    if value is None:
        return []
    if isinstance(value, str):
        if value == "":
            return []
        return [s.strip() for s in value.split(",") if s.strip()]
    return value


class TicketFilters(BaseModel):
    """Validated query parameters for /tickets and /tickets/stats."""

    model_config = ConfigDict(extra="forbid")

    state: list[TicketState] = Field(default_factory=list)
    priority: list[TicketPriority] = Field(default_factory=list)
    category_id: list[UUID] = Field(default_factory=list)

    opened_after: datetime | None = None
    opened_before: datetime | None = None

    # "me" / "unassigned" / a UUID; resolved to a concrete predicate
    # by the service. Sprint 7.5.5 doesn't include a tenant directory
    # endpoint yet (A7 lands in Alt-Faz 4), so the picker on the
    # frontend stays "me / unassigned / any" until then.
    assignee: AssigneeFilter = None

    search: str | None = Field(default=None, max_length=200)

    # Pagination — basic offset/limit. Cursor pagination is C5 (Sprint 8).
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    # Sort. Literal-typed so SQL injection / unknown-column errors are
    # impossible at the route layer.
    order_by: OrderBy = "last_state_change_at"
    order: OrderDirection = "desc"

    @field_validator("state", "priority", "category_id", mode="before")
    @classmethod
    def _split_csv_lists(cls, v: object) -> object:
        return _split_csv(v)


GroupBy = Literal["state", "priority", "category", "assignee"]


class StatsRequest(BaseModel):
    """Standalone group_by + filter combo for /tickets/stats."""

    model_config = ConfigDict(extra="forbid")

    group_by: GroupBy
    filters: TicketFilters = Field(default_factory=TicketFilters)
