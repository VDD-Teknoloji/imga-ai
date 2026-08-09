"""ReviewService — analyze→ticket bridge with five decision branches.

Sprint 7.5.5 / Alt-Faz 3. ``record_and_decide`` is the only entry
point: it persists one ``reviews`` row per call and (on the CREATE
branch) mints one ticket. The five decision branches are evaluated
in this fixed order so audit traces stay deterministic:

  1. ``skipped_belirsiz``  — primary category is "belirsiz". No mode
     auto-creates from this; user must triage manually if they want.
  2. ``skipped_mode``      — tenant is in ``manual`` automation_mode.
  3. ``skipped_threshold`` — ``decide_auto_create_state`` returned
     ``should_create=False`` (semi_auto under threshold or full_auto
     non-negative sentiment).
  4. ``skipped_dedup``     — same text_hash already produced a ticket
     within ``DEDUP_WINDOW`` (24 hours). The new review row is still
     written (audit) and points at the existing ticket via
     ``ticket_id``.
  5. ``create``            — all guards passed; new ticket created.

Why this order: each guard is "cheaper" than the next. ``belirsiz``
and ``mode`` are read-from-snapshot checks; ``threshold`` is pure
math; ``dedup`` is the only DB lookup; ``create`` is the most
expensive (ticket insert + audit write). Falling through guards
in this order keeps the no-op path (manual mode + neutral text)
free of database round-trips beyond the one mandatory review row.

Tenant config is read via ``TenantConfigService.get_config`` which
is cache-backed (5-min TTL, invalidated on automation_mode update).
The ``automation_mode`` value is **snapshotted** onto the review
row at decision time so historical audits remain self-explanatory
even after the tenant flips modes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from imga_core import AnalysisResult, review_text_hash
from imga_core.categorizers import TaxonomyEntry, apply_company_heuristic
from imga_db.models import (
    AutomationMode,
    Category,
    CategoryTaxonomy,
    Review,
    ReviewDecision,
    Tenant,
    Ticket,
    TicketPriority,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.services.tenant_config_service import TenantConfigService
from imga_api.services.ticket_routing_service import (
    apply_routing,
    resolve_rule,
)
from imga_api.services.ticket_service import (
    TicketService,
    decide_auto_create_state,
)

_logger = logging.getLogger(__name__)

# 24-hour dedup window. Same text submitted twice in this window
# collapses to a single ticket; outside the window it's a fresh ticket
# (the original might have been cancelled / closed already).
DEDUP_WINDOW = timedelta(hours=24)

# Length cap for ticket title; the full text always lands in summary.
_TITLE_MAX_LEN = 200


class ReviewServiceError(Exception):
    """Generic ReviewService failure."""


class CategoryNotConfiguredError(ReviewServiceError):
    """The classifier returned a category code that's not present in
    this tenant's visible category set. Should be unreachable in
    practice — categories are seeded globally — but we raise loudly
    rather than silently dropping a ticket on the floor."""


class ReviewNotFoundError(ReviewServiceError):
    """promote_to_ticket called with a review_id the active tenant can
    not see (or doesn't exist). Surfaces as 404."""


class ReviewAlreadyTicketedError(ReviewServiceError):
    """Review already has ticket_id set; the manual-promotion endpoint
    must not double-mint. Surfaces as 409."""


@dataclass(frozen=True, slots=True)
class ReviewBridgeResult:
    """Wire-shape return value from record_and_decide.

    ``ticket_id`` is set on ``CREATE`` (newly minted) and
    ``SKIPPED_DEDUP`` (pointer to existing). All other branches
    leave it None.

    ``company_perspective_code`` / ``company_perspective_label_tr`` mirror
    the heuristic match the bridge persisted on the row (Sprint 8.3.5.6);
    surfacing them here lets the /analyze route render the matched code
    without a follow-up GET on the new review.
    """

    review_id: UUID
    decision: ReviewDecision
    decision_reason: str | None
    ticket_id: UUID | None
    analyzed_at: datetime
    company_perspective_code: str | None = None
    company_perspective_label_tr: str | None = None


class ReviewService:
    """Bridges /tenants/me/analyze output into the tickets table.

    Lives on the imga_app session (RLS-bound). Session must already
    have ``app.current_tenant_id`` SET via ``bind_tenant`` before
    record_and_decide runs — we don't bind in the service so the
    transaction boundary stays in the route.
    """

    def __init__(
        self,
        session: AsyncSession,
        audit: AuditService,
        ticket_service: TicketService,
        config_service: TenantConfigService,
    ) -> None:
        self._session = session
        self._audit = audit
        self._tickets = ticket_service
        self._config = config_service

    async def record_and_decide(
        self,
        *,
        tenant_id: UUID,
        text: str,
        analysis: AnalysisResult,
        actor_user_id: UUID | None,
        now: datetime | None = None,
        nps_score: int | None = None,
        business_segment: str | None = None,
        product_line: str | None = None,
        channel: str | None = None,
        customer_tier: str | None = None,
        review_date: datetime | None = None,
        perspective_override: tuple[str, str] | None = None,
    ) -> ReviewBridgeResult:
        """Persist one review row and (on the CREATE branch) one ticket.

        ``actor_user_id`` is None for system-driven calls (Sprint 8.3.1
        batch worker when the upload's triggering user has been deleted
        between upload and processing). The audit row + Review row both
        accept NULL there; the FK constraint on ``users`` uses ON DELETE
        SET NULL, so a valid UUID is not strictly required.

        Sprint 9.4 D — the four dimension kwargs come from the batch
        upload's per-row ParsedRow (or the single-review POST body's
        dimension fields). Default None preserves the pre-9.4 contract
        for callers that don't carry dimensions yet.

        ``review_date`` is the review's own date (upload's ``tarih``
        column). None — the manual /analyze path and uploads without a
        date column — falls back to ``moment``, i.e. ingest time.

        Sprint 13.1 — ``perspective_override`` is the ``(code,
        label_tr)`` pair the unified LLM classifier already picked for
        this row. When present it replaces the keyword heuristic so the
        batch worker and this bridge agree on one answer; None keeps
        the 8.3.5.6 behaviour (compute the heuristic here)."""
        moment = now or datetime.now(UTC)
        text_hash = review_text_hash(text)

        # Tenant config snapshot. The cache absorbs the cost across
        # repeat /analyze calls within the 5-min TTL; the snapshot
        # is intentionally read once here so the decision below uses
        # a consistent automation_mode for the duration of the call.
        config = await self._config.get_config(tenant_id)
        mode_str = str(config["automation_mode"])
        automation_mode = AutomationMode(mode_str)

        primary_code, primary_confidence = _extract_primary(analysis)

        # Sprint 8.3.5.6. Heuristic company-perspective match —
        # parallel dimension to BERT primary, drives the dashboard's
        # "Şirket Perspektifi" column. Both fields are None when the
        # tenant's taxonomy is empty or no keyword matched (the latter
        # is the dominant case for short / off-topic reviews).
        perspective_code: str | None
        perspective_label_tr: str | None
        if perspective_override is not None:
            perspective_code, perspective_label_tr = perspective_override
        else:
            perspective_code, perspective_label_tr = (
                await self._compute_company_perspective(
                    tenant_id=tenant_id, text=text
                )
            )

        # --- decision tree (order matters; see module docstring) ---
        decision: ReviewDecision
        decision_reason: str | None
        ticket_id: UUID | None = None

        if primary_code == "belirsiz":
            decision = ReviewDecision.SKIPPED_BELIRSIZ
            decision_reason = "primary_category_belirsiz"
        elif automation_mode == AutomationMode.MANUAL:
            decision = ReviewDecision.SKIPPED_MODE
            decision_reason = "manual_mode"
        else:
            threshold = decide_auto_create_state(
                automation_mode=automation_mode,
                sentiment_score=analysis.sentiment_score,
                confidence=primary_confidence,
            )
            if not threshold.should_create:
                decision = ReviewDecision.SKIPPED_THRESHOLD
                decision_reason = threshold.reason
            else:
                existing_ticket_id = await self._find_dedup_ticket(
                    tenant_id=tenant_id,
                    text_hash=text_hash,
                    now=moment,
                )
                if existing_ticket_id is not None:
                    decision = ReviewDecision.SKIPPED_DEDUP
                    decision_reason = "text_hash_within_24h"
                    ticket_id = existing_ticket_id
                else:
                    category_id = await self._resolve_category_id(primary_code)
                    title, summary = _split_title_summary(text)
                    ticket = await self._tickets.create(
                        tenant_id=tenant_id,
                        category_id=category_id,
                        title=title,
                        summary=summary,
                        priority=TicketPriority.NORMAL,
                        review_id=None,  # back-pointed below once review.id exists
                        created_by_user_id=None,  # system-generated
                        opened_at=moment,
                    )
                    ticket_id = ticket.id
                    decision = ReviewDecision.CREATE
                    decision_reason = threshold.reason
                    await self._route_new_ticket(
                        tenant_id=tenant_id,
                        ticket=ticket,
                        category_code=primary_code,
                    )

        # Persist the review row regardless of branch — every analyze
        # call leaves an audit trail.
        review = Review(
            tenant_id=tenant_id,
            text=text,
            text_hash=text_hash,
            sentiment_label=analysis.sentiment_label,
            sentiment_score=float(analysis.sentiment_score),
            primary_category=primary_code,
            primary_confidence=float(primary_confidence),
            automation_mode=mode_str,
            decision=decision,
            decision_reason=decision_reason,
            ticket_id=ticket_id,
            submitted_by_user_id=actor_user_id,
            analyzed_at=moment,
            review_date=review_date or moment,
            overrides_applied=[hit.model_dump() for hit in analysis.overrides_applied],
            nps_score=nps_score,
            company_perspective_code=perspective_code,
            business_segment=business_segment,
            product_line=product_line,
            channel=channel,
            customer_tier=customer_tier,
        )
        self._session.add(review)
        await self._session.flush()

        # Wire review.id back onto the freshly-minted ticket so the
        # ticket detail page can fetch the full review payload (and so
        # Sprint 8 dedup analytics can join cleanly). The migration
        # 0006 deliberately left review_id without an FK precisely so
        # we could set it from this direction without an additional
        # constraint round-trip.
        if decision == ReviewDecision.CREATE and ticket_id is not None:
            ticket_obj = await self._session.get(Ticket, ticket_id)
            if ticket_obj is not None:
                ticket_obj.review_id = review.id
                await self._session.flush()

        # Audit log every decision branch with a stable shape so
        # log-aggregation can group by `details->>'decision'`.
        await self._audit.log(
            action="review.analyzed",
            resource_type="review",
            resource_id=review.id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={
                "decision": str(decision),
                "review_id": str(review.id),
                "ticket_id": str(ticket_id) if ticket_id else None,
            },
        )

        return ReviewBridgeResult(
            review_id=review.id,
            decision=decision,
            decision_reason=decision_reason,
            ticket_id=ticket_id,
            analyzed_at=moment,
            company_perspective_code=perspective_code,
            company_perspective_label_tr=perspective_label_tr,
        )

    # --- manual promotion ---------------------------------------------

    async def promote_to_ticket(
        self,
        *,
        tenant_id: UUID,
        review_id: UUID,
        actor_user_id: UUID,
        now: datetime | None = None,
    ) -> Ticket:
        """Open a ticket for a review the bridge previously skipped.

        Used by ``POST /tenants/me/reviews/{id}/create-ticket`` when a
        user wants to override the bridge's no-op decision (skipped_mode,
        skipped_threshold, skipped_belirsiz) with their domain expertise.

        Idempotency: if the review already points at a ticket, raises
        ``ReviewAlreadyTicketedError`` so the route can return 409. The
        ``manually_promoted_to_ticket`` decision_reason marks the row
        for analytics; the original ``decision`` column stays so the
        bridge's call is preserved as audit trail.
        """
        moment = now or datetime.now(UTC)
        review = await self._session.get(Review, review_id)
        if review is None or review.tenant_id != tenant_id or review.deleted_at is not None:
            raise ReviewNotFoundError(f"review {review_id} not found")
        if review.ticket_id is not None:
            raise ReviewAlreadyTicketedError(
                f"review {review_id} already linked to ticket {review.ticket_id}"
            )

        # Reuse the bridge's category-resolution + title/summary helpers
        # so a manually-promoted ticket looks identical to an
        # automatically-created one in the tickets list.
        category_code = review.primary_category or "belirsiz"
        category_id = await self._resolve_category_id(category_code)
        title, summary = _split_title_summary(review.text)

        ticket = await self._tickets.create(
            tenant_id=tenant_id,
            category_id=category_id,
            title=title,
            summary=summary,
            priority=TicketPriority.NORMAL,
            review_id=review.id,
            created_by_user_id=actor_user_id,
            opened_at=moment,
        )
        await self._route_new_ticket(
            tenant_id=tenant_id, ticket=ticket, category_code=category_code
        )
        review.ticket_id = ticket.id
        # Preserve the original `decision` (skipped_mode etc.) so the
        # audit trail still shows the bridge's call. `decision_reason`
        # gets the new label so analytics can count manual overrides
        # separately from the bridge's reasons.
        review.decision_reason = "manually_promoted_to_ticket"
        await self._session.flush()

        await self._audit.log(
            action="review.manual_ticket_creation",
            resource_type="review",
            resource_id=review.id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            details={
                "review_id": str(review.id),
                "ticket_id": str(ticket.id),
                "original_decision": str(review.decision),
            },
        )
        return ticket

    # --- helpers --------------------------------------------------------

    async def _route_new_ticket(
        self,
        *,
        tenant_id: UUID,
        ticket: Ticket,
        category_code: str,
    ) -> None:
        """Kategori yönlendirme hook'u — üç mint yolunun ortak noktası.
        Yönlendirme hatası ticket mint'ini geri almamalı: kural/atama
        problemi loglanır, review + ticket akışı devam eder."""
        try:
            rule = await resolve_rule(
                self._session, tenant_id=tenant_id, category_code=category_code
            )
            if rule is None:
                return
            tenant = await self._session.get(Tenant, tenant_id)
            if tenant is None:
                return
            await apply_routing(
                self._session,
                tenant=tenant,
                ticket=ticket,
                category_code=category_code,
                rule=rule,
                ticket_service=self._tickets,
            )
        except Exception:
            _logger.exception(
                "ticket routing failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "ticket_id": str(ticket.id),
                    "category_code": category_code,
                },
            )

    async def _find_dedup_ticket(
        self,
        *,
        tenant_id: UUID,
        text_hash: str,
        now: datetime,
    ) -> UUID | None:
        """Return the most recent ticket_id for this text_hash within
        the 24-hour window, or None if no prior review reached/shared
        a ticket. The partial index ``ix_reviews_tenant_dedup`` already
        filters on ``ticket_id IS NOT NULL`` so this lookup is cheap."""
        cutoff = now - DEDUP_WINDOW
        stmt = (
            select(Review.ticket_id)
            .where(Review.tenant_id == tenant_id)
            .where(Review.text_hash == text_hash)
            .where(Review.ticket_id.is_not(None))
            .where(Review.analyzed_at >= cutoff)
            .order_by(Review.analyzed_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _compute_company_perspective(
        self, *, tenant_id: UUID, text: str
    ) -> tuple[str | None, str | None]:
        """Load the tenant's CategoryTaxonomy rows and run the heuristic
        reranker. Returns ``(code, label_tr)`` for the match, or
        ``(None, None)`` when nothing matched / the taxonomy is empty.

        Reads inside the bound app session; RLS keeps the query scoped
        to ``tenant_id`` automatically. Service stays headless of any
        explicit ``WHERE tenant_id = :t`` since the policy already
        adds it — passing tenant_id here is just for the rare path
        where bind_tenant hasn't run (it always has, in practice).
        """
        stmt = select(
            CategoryTaxonomy.code,
            CategoryTaxonomy.label_tr,
            CategoryTaxonomy.keywords,
            CategoryTaxonomy.priority,
        ).where(CategoryTaxonomy.tenant_id == tenant_id)
        rows = (await self._session.execute(stmt)).all()
        if not rows:
            return None, None
        taxonomy: list[TaxonomyEntry] = [
            TaxonomyEntry(
                code=r.code,
                label_tr=r.label_tr,
                keywords=list(r.keywords),
                priority=r.priority,
            )
            for r in rows
        ]
        hit = apply_company_heuristic(review_text=text, taxonomy=taxonomy)
        if hit is None:
            return None, None
        return hit.code, hit.label_tr

    async def _resolve_category_id(self, code: str) -> UUID:
        """Find the category id for a code visible to the bound tenant.

        RLS already restricts the result set to globals + own customs.
        Tenant custom codes are forbidden from clashing with globals
        (TenantConfigService.create_custom_category guards that), so
        any code returned by the classifier resolves to a single row.
        """
        stmt = (
            select(Category.id)
            .where(Category.code == code)
            .where(Category.deleted_at.is_(None))
            .limit(1)
        )
        cat_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if cat_id is None:
            raise CategoryNotConfiguredError(
                f"category {code!r} is not configured for this tenant"
            )
        return cat_id


def _extract_primary(analysis: AnalysisResult) -> tuple[str, float]:
    """Pull the primary category code + confidence off the analysis
    payload, handling the rare case where the classifier was disabled
    on the pipeline (categorization=None → treat as belirsiz)."""
    cat = analysis.categorization
    if cat is None:
        return "belirsiz", 0.0
    return cat.primary, float(cat.primary_confidence)


def _split_title_summary(text: str) -> tuple[str, str | None]:
    """Title is the first 200 chars (no ellipsis — keeps it greppable);
    summary holds the full text iff the text was longer."""
    if len(text) <= _TITLE_MAX_LEN:
        return text, None
    return text[:_TITLE_MAX_LEN], text


__all__ = [
    "DEDUP_WINDOW",
    "CategoryNotConfiguredError",
    "ReviewAlreadyTicketedError",
    "ReviewBridgeResult",
    "ReviewNotFoundError",
    "ReviewService",
    "ReviewServiceError",
]
