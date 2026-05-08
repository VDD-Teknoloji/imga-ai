"""ActionExtractionService — idempotent action-item extraction.

Sprint 9.0.5-B G. Strategic reports + executive briefings carry an
LLM-authored "top actions" list as prose. Past behaviour minted a
fresh batch of ``action_items`` rows every time the route fired,
so a re-render of the same source produced duplicate follow-up
tasks. This service is the dedupe layer:

  1. Caller hands in (source_type, source_id, action_payloads,
     content_text).
  2. Service computes a fingerprint:
     ``sha256(content_text + extraction_version)``.
  3. Service tries INSERT ... ON CONFLICT DO NOTHING into
     ``action_items_extraction_log`` keyed on
     (tenant_id, source_type, source_id, fingerprint).
  4. If the row already exists (re-render with same content),
     SELECT it back and return its ``action_item_ids``.
  5. Otherwise, insert ActionItem rows + the log row, return the
     newly-minted ids.

Calling this twice with identical content is a no-op on the DB
side — same action_item_ids returned, no new rows. A content edit
yields a new fingerprint and a fresh extraction.

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from imga_db.models import ActionItem, ActionItemExtractionLog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


# Sprint 9.0.5-B G — bumped whenever the extraction prompt /
# parsing logic changes in a way that should re-extract previously
# processed sources. The fingerprint is
# ``sha256(content_text + EXTRACTION_VERSION)`` so a version bump
# invalidates every existing extraction row for the same source.
EXTRACTION_VERSION = "v1"

_VALID_SOURCE_TYPES = frozenset({"strategic_report", "executive_briefing"})


class ActionExtractionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def extract(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        content_text: str,
        action_payloads: list[dict[str, Any]],
    ) -> list[UUID]:
        """Idempotent extraction. Returns the list of ActionItem
        ids — either freshly inserted (first call for this content)
        or re-fetched from the existing log row (subsequent calls).

        ``action_payloads`` shape per item:
            {
              "title": str,           # required
              "description": str,     # required
              "rationale": str | None,
              "priority": "high"|"medium"|"low",
              "estimated_impact": "high"|"medium"|"low" | None,
            }

        Anything not on this contract is ignored.

        Raises:
            ValueError: ``source_type`` outside the DB CHECK
                constraint set, or ``content_text`` empty.
        """
        if source_type not in _VALID_SOURCE_TYPES:
            raise ValueError(
                f"unsupported source_type {source_type!r}; "
                f"expected one of {sorted(_VALID_SOURCE_TYPES)}"
            )
        if not content_text or not content_text.strip():
            raise ValueError(
                "content_text is empty; extraction would produce "
                "an empty fingerprint"
            )

        fingerprint = self._compute_fingerprint(content_text)

        # Try the cheap path first — has this exact extraction
        # already happened? Single SELECT against the UNIQUE index.
        existing = await self._lookup_log(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            fingerprint=fingerprint,
        )
        if existing is not None:
            _logger.info(
                "action_extraction: reusing existing extraction "
                "log for %s/%s (fingerprint=%s, %d items)",
                source_type, source_id, fingerprint[:12],
                len(existing),
                extra={"tenant_id": str(tenant_id)},
            )
            return existing

        # Mint new ActionItem rows. Service stays inside the
        # caller's transaction so RLS binds correctly + a failure
        # rolls back atomically (no half-inserted log row pointing
        # at orphan items).
        new_ids = await self._insert_action_items(
            tenant_id=tenant_id,
            action_payloads=action_payloads,
            source_type=source_type,
            source_id=source_id,
        )

        # Persist the log row. INSERT...ON CONFLICT DO NOTHING +
        # subsequent SELECT covers the rare race where two parallel
        # generation runs raced past the existence check above —
        # the second one's items become orphans but no exception
        # surfaces; the existing log row's ids win.
        stmt = pg_insert(ActionItemExtractionLog).values(
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            extraction_fingerprint=fingerprint,
            action_item_ids=new_ids,
        ).on_conflict_do_nothing(
            index_elements=[
                "tenant_id",
                "source_type",
                "source_id",
                "extraction_fingerprint",
            ],
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:
            # Race lost — re-fetch the winning log row's ids and
            # return those. Our just-inserted ActionItems become
            # orphans (will be cleaned up by a sweeper or
            # TODO-tagged for ops follow-up).
            _logger.warning(
                "action_extraction: race detected on log insert "
                "for %s/%s — reusing winning row",
                source_type, source_id,
                extra={"tenant_id": str(tenant_id)},
            )
            existing = await self._lookup_log(
                tenant_id=tenant_id,
                source_type=source_type,
                source_id=source_id,
                fingerprint=fingerprint,
            )
            return existing or new_ids

        await self._session.flush()
        _logger.info(
            "action_extraction: minted %d ActionItem rows for "
            "%s/%s (fingerprint=%s)",
            len(new_ids), source_type, source_id, fingerprint[:12],
            extra={"tenant_id": str(tenant_id)},
        )
        return new_ids

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_fingerprint(content_text: str) -> str:
        payload = f"{EXTRACTION_VERSION}|{content_text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _lookup_log(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        fingerprint: str,
    ) -> list[UUID] | None:
        stmt = (
            select(ActionItemExtractionLog.action_item_ids)
            .where(ActionItemExtractionLog.tenant_id == tenant_id)
            .where(ActionItemExtractionLog.source_type == source_type)
            .where(ActionItemExtractionLog.source_id == source_id)
            .where(
                ActionItemExtractionLog.extraction_fingerprint == fingerprint
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return list(row) if row is not None else None

    async def _insert_action_items(
        self,
        *,
        tenant_id: UUID,
        action_payloads: list[dict[str, Any]],
        source_type: str,
        source_id: UUID,
    ) -> list[UUID]:
        if not action_payloads:
            return []
        new_ids: list[UUID] = []
        source_field = (
            "source_briefing_id"
            if source_type == "executive_briefing"
            else "source_report_id"
        )
        for payload in action_payloads:
            title = str(payload.get("title") or "").strip()
            description = str(payload.get("description") or "").strip()
            if not title or not description:
                # Defensive: an LLM hallucination with empty
                # title/description shouldn't crash the whole
                # batch. Skip with a log so an operator can
                # reconcile if they care.
                _logger.warning(
                    "action_extraction: skipping payload with "
                    "missing title/description: %s",
                    json.dumps(payload, ensure_ascii=False)[:200],
                )
                continue
            kwargs: dict[str, Any] = {
                "tenant_id": tenant_id,
                "title": title[:256],
                "description": description,
                "rationale": (
                    str(payload["rationale"])
                    if payload.get("rationale")
                    else None
                ),
                "priority": str(payload.get("priority") or "medium"),
                "estimated_impact": (
                    str(payload["estimated_impact"])
                    if payload.get("estimated_impact")
                    else None
                ),
                source_field: source_id,
            }
            item = ActionItem(**kwargs)
            self._session.add(item)
            await self._session.flush()
            new_ids.append(item.id)
        return new_ids


__all__ = [
    "ActionExtractionService",
    "EXTRACTION_VERSION",
]
