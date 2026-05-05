"""SLA Rules Engine — Sprint 8.3.7-A.

Evaluates a review (or freshly-created ticket) against the active
tenant's ``sla_rules`` rows. The engine is data-driven: it reads
a small ``ReviewSlaContext`` dataclass extracted by the caller from
the live Review/Ticket pair and returns a list of ``SlaMatch`` objects
— one per rule whose match conditions all pass.

Action wiring across sprints:

  * ``warn_only`` — live this sprint. The engine logs the match and
    appends to the returned list; no side effects.
  * ``create_ticket`` / ``escalate`` / ``notify_email`` — accepted
    by ``execute_action`` with a NotImplementedError until those
    sprints (8.3.9 / 8.6) wire the downstream flow. This keeps the
    DB shape forward-compatible — tenants can draft rules now and
    have them activate automatically when the action ships.

logger.exception() in every catch path — Sprint 8.3.6.6 round-3
baseline note.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from imga_db.models import SlaRule
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewSlaContext:
    """Snapshot of the review (and any related ticket) the engine
    evaluates against. The caller extracts these fields once; the
    engine treats them as immutable."""

    tenant_id: UUID
    review_id: UUID
    # Ticket-derived fields when the review has an auto-ticket; ``None``
    # otherwise. ``priority`` is one of low/normal/high/urgent.
    ticket_priority: str | None = None
    # Heuristic + BERT outputs.
    taxonomy_code: str | None = None
    company_perspective_code: str | None = None
    # NPS — None if the upload row didn't carry one.
    nps_score: int | None = None
    # Free-form extras for the action_config templating downstream
    # (Sprint 8.3.9+); engine doesn't read these for matching.
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SlaMatch:
    """One rule that fired against a review. ``breach_severity`` is a
    coarse signal the downstream UI uses to colour the matched row;
    today it derives from whether response or resolution thresholds
    are set (response is the more urgent default)."""

    rule_id: UUID
    rule_name: str
    action_type: str
    action_config: dict[str, Any]
    response_sla_minutes: int | None
    resolution_sla_minutes: int | None
    breach_severity: str  # "response" / "resolution" / "both"


class SlaEngine:
    """Stateless evaluator. One instance per request is fine — the
    session is bound at construction time. Callers must have already
    set ``app.current_tenant_id`` so the RLS policy filters the rules
    to the active tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate(
        self, ctx: ReviewSlaContext
    ) -> list[SlaMatch]:
        """Return every active SLA rule the review matches. Order
        mirrors ``created_at`` (oldest first) so deterministic in
        tests and stable in the UI listing."""
        try:
            rules = await self._load_active_rules(ctx.tenant_id)
        except Exception:
            _logger.exception(
                "sla_engine: failed to load rules",
                extra={"tenant_id": str(ctx.tenant_id)},
            )
            raise

        matches: list[SlaMatch] = []
        for rule in rules:
            if not _rule_matches(rule, ctx):
                continue
            matches.append(_to_match(rule))
            _logger.info(
                "sla_engine: match",
                extra={
                    "tenant_id": str(ctx.tenant_id),
                    "review_id": str(ctx.review_id),
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "action_type": rule.action_type,
                },
            )
        return matches

    async def _load_active_rules(self, tenant_id: UUID) -> list[SlaRule]:
        stmt = (
            select(SlaRule)
            .where(SlaRule.tenant_id == tenant_id)
            .where(SlaRule.is_active.is_(True))
            .order_by(SlaRule.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


def _rule_matches(rule: SlaRule, ctx: ReviewSlaContext) -> bool:
    """Match every populated dimension on the rule. Empty / NULL on
    the rule means "any" for that dimension (so a rule with all
    matchers cleared fires on every review).

    Match logic:

      * priority — exact string match against ``ctx.ticket_priority``.
        Rule with priority set but ctx.ticket_priority None → no match
        (we'd false-positive a non-ticket review otherwise).
      * taxonomy_codes — at least one rule code must equal the ctx
        code. Empty/None array → any.
      * company_perspective_codes — same.
      * nps_score_max — match when ctx.nps_score is set AND
        ctx.nps_score <= rule.match_nps_score_max. Rule set + ctx
        unset → no match (no false-positive on missing data).
    """
    if (
        rule.match_priority is not None
        and ctx.ticket_priority != rule.match_priority
    ):
        return False

    if rule.match_taxonomy_codes:
        if ctx.taxonomy_code is None:
            return False
        if ctx.taxonomy_code not in rule.match_taxonomy_codes:
            return False

    if rule.match_company_perspective_codes:
        if ctx.company_perspective_code is None:
            return False
        if (
            ctx.company_perspective_code
            not in rule.match_company_perspective_codes
        ):
            return False

    if rule.match_nps_score_max is not None:
        if ctx.nps_score is None:
            return False
        if ctx.nps_score > rule.match_nps_score_max:
            return False

    return True


def _to_match(rule: SlaRule) -> SlaMatch:
    severity = _breach_severity(rule)
    return SlaMatch(
        rule_id=rule.id,
        rule_name=rule.name,
        action_type=rule.action_type,
        action_config=dict(rule.action_config or {}),
        response_sla_minutes=rule.response_sla_minutes,
        resolution_sla_minutes=rule.resolution_sla_minutes,
        breach_severity=severity,
    )


def _breach_severity(rule: SlaRule) -> str:
    has_response = rule.response_sla_minutes is not None
    has_resolution = rule.resolution_sla_minutes is not None
    if has_response and has_resolution:
        return "both"
    if has_response:
        return "response"
    if has_resolution:
        return "resolution"
    # Defensive fallback — DB CHECK guarantees one is set, but if a
    # future migration loosens that guarantee we don't crash.
    return "unknown"


async def execute_action(
    match: SlaMatch,
    payload: Any | None = None,
    *,
    session: AsyncSession | None = None,
    tenant_id: UUID | None = None,
    review_id: UUID | None = None,
    dispatch_mode: str = "automatic",
) -> None:
    """Run the matched rule's action. ``warn_only`` no-ops (the
    engine already logged). ``slack_webhook`` / ``teams_webhook``
    dispatch via the shared WebhookDispatcher when ``payload`` is
    provided. ``create_ticket`` / ``escalate`` stay deferred
    (Sprint 8.3.x roadmap); ``notify_email`` stays deferred
    (Sprint 8.6, alongside Mailcow). Kept as a free function so
    the engine layer stays focused on matching.

    The ``payload`` argument carries the SlaWebhookPayload built by
    the caller — typed loosely here so the engine module doesn't
    take a hard dependency on the dispatcher (and tests can pass a
    stub without importing httpx).

    Sprint 9.0 — when ``dispatch_mode == 'manual'`` and the matched
    action is a webhook, the call queues into ``pending_webhook_events``
    instead of firing httpx.post; the operator approves / dismisses
    from /pending-webhooks. ``session`` + ``tenant_id`` are required
    for the manual path so the queue insert can use the RLS-bound
    transaction the caller already opened. Falling back to the
    automatic path when either is missing keeps the call site simple
    for legacy code paths that haven't migrated yet.
    """
    if match.action_type == "warn_only":
        return
    if match.action_type == "slack_webhook":
        await _route_webhook(
            "slack", match, payload,
            session=session, tenant_id=tenant_id,
            review_id=review_id, dispatch_mode=dispatch_mode,
        )
        return
    if match.action_type == "teams_webhook":
        await _route_webhook(
            "teams", match, payload,
            session=session, tenant_id=tenant_id,
            review_id=review_id, dispatch_mode=dispatch_mode,
        )
        return
    if match.action_type in {"create_ticket", "escalate"}:
        raise NotImplementedError(
            f"action_type={match.action_type!r} lands in Sprint 8.3.x"
        )
    if match.action_type == "notify_email":
        raise NotImplementedError(
            "action_type='notify_email' lands in Sprint 8.6 alongside Mailcow"
        )
    raise ValueError(f"unknown action_type={match.action_type!r}")


async def _route_webhook(
    kind: str,
    match: SlaMatch,
    payload: Any | None,
    *,
    session: AsyncSession | None,
    tenant_id: UUID | None,
    review_id: UUID | None,
    dispatch_mode: str,
) -> None:
    """Route a matched webhook action to the right dispatch path —
    automatic (live POST) or manual (queue into pending_webhook_events).
    Sprint 9.0."""
    if payload is None:
        _logger.warning(
            "sla_engine: %s_webhook fired without payload — skipping dispatch",
            kind,
            extra={"rule_id": str(match.rule_id)},
        )
        return

    config = match.action_config or {}
    url = config.get("webhook_url")
    if not isinstance(url, str) or not url.strip():
        _logger.warning(
            "sla_engine: %s_webhook rule %s missing webhook_url",
            kind, match.rule_id,
        )
        return

    can_queue = (
        dispatch_mode == "manual"
        and session is not None
        and tenant_id is not None
    )
    if can_queue:
        await _queue_pending_webhook(
            kind=kind,
            session=session,  # type: ignore[arg-type]
            tenant_id=tenant_id,  # type: ignore[arg-type]
            review_id=review_id,
            match=match,
            url=url,
            channel=config.get("channel"),
            payload=payload,
        )
        return

    await _dispatch_webhook(kind, url, match, payload, channel=config.get("channel"))


async def _dispatch_webhook(
    kind: str,
    url: str,
    match: SlaMatch,
    payload: Any,
    *,
    channel: str | None = None,
) -> None:
    """Live dispatch via WebhookDispatcher. Lazy-imported so the
    warn_only-only deployment path doesn't pull httpx in."""
    from imga_api.services.webhook_dispatcher import WebhookDispatcher

    dispatcher = WebhookDispatcher()
    try:
        if kind == "slack":
            await dispatcher.dispatch_slack(url, payload, channel=channel)
        else:
            await dispatcher.dispatch_teams(url, payload)
    except Exception:
        _logger.exception(
            "%s webhook dispatch swallowed",
            kind,
            extra={"rule_id": str(match.rule_id)},
        )


async def _queue_pending_webhook(
    *,
    kind: str,
    session: AsyncSession,
    tenant_id: UUID,
    review_id: UUID | None,
    match: SlaMatch,
    url: str,
    channel: str | None,
    payload: Any,
) -> None:
    """Insert a queued pending_webhook_events row. Sprint 9.0 manual
    dispatch path. Lazy-imports the service module to keep the engine
    layer free of explicit DB-model dependencies."""
    from imga_db.models import PendingWebhookTarget

    from imga_api.services.audit_service import AuditService
    from imga_api.services.pending_webhook_service import PendingWebhookService

    target = (
        PendingWebhookTarget.SLACK if kind == "slack"
        else PendingWebhookTarget.TEAMS
    )
    audit = AuditService(session)
    service = PendingWebhookService(session, audit)
    try:
        await service.queue_event(
            tenant_id=tenant_id,
            sla_rule_id=match.rule_id,
            review_id=review_id,
            target=target,
            webhook_url=url,
            channel=channel,
            payload=payload,
        )
    except Exception:
        _logger.exception(
            "sla_engine: failed to queue pending %s webhook",
            kind,
            extra={
                "tenant_id": str(tenant_id),
                "rule_id": str(match.rule_id),
            },
        )


__all__ = [
    "ReviewSlaContext",
    "SlaEngine",
    "SlaMatch",
    "execute_action",
]
