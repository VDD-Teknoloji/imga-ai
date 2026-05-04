"""Sprint 8.3.7-A — SlaEngine unit tests.

Pure logic — no DB, no auth. Builds in-memory SlaRule rows + a
ReviewSlaContext, asserts the matcher's decision and the resulting
SlaMatch shape (breach_severity, action wiring).

The DB-bound CRUD path is covered by test_tenant_sla_rules_routes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from imga_db.models import SlaRule

from imga_api.services.sla_engine import (
    ReviewSlaContext,
    execute_action,
)


def _rule(**overrides: Any) -> SlaRule:
    """Construct an in-memory SlaRule. ``id`` and timestamps are set
    so the object passes through the engine without touching a session."""
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "name": "test rule",
        "match_priority": None,
        "match_taxonomy_codes": None,
        "match_company_perspective_codes": None,
        "match_nps_score_max": None,
        "response_sla_minutes": 60,
        "resolution_sla_minutes": None,
        "action_type": "warn_only",
        "action_config": {},
        "is_active": True,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return SlaRule(**base)


def _ctx(**overrides: Any) -> ReviewSlaContext:
    base = {
        "tenant_id": uuid4(),
        "review_id": uuid4(),
        "ticket_priority": None,
        "taxonomy_code": None,
        "company_perspective_code": None,
        "nps_score": None,
    }
    base.update(overrides)
    return ReviewSlaContext(**base)


# --- pure matcher logic ---------------------------------------------------


def test_rule_matches_when_no_filters_set() -> None:
    """A rule with every match_* field NULL fires on every review —
    the equivalent of "any review" matcher."""
    from imga_api.services.sla_engine import _rule_matches

    assert _rule_matches(_rule(), _ctx()) is True


def test_rule_priority_match_requires_ticket_priority() -> None:
    """Rule has match_priority='high' but ctx has no ticket → no
    match (don't false-positive a non-ticket review)."""
    from imga_api.services.sla_engine import _rule_matches

    rule = _rule(match_priority="high")
    assert _rule_matches(rule, _ctx(ticket_priority=None)) is False
    assert _rule_matches(rule, _ctx(ticket_priority="normal")) is False
    assert _rule_matches(rule, _ctx(ticket_priority="high")) is True


def test_rule_taxonomy_codes_match_any_in_list() -> None:
    from imga_api.services.sla_engine import _rule_matches

    rule = _rule(match_taxonomy_codes=["a", "b", "c"])
    assert _rule_matches(rule, _ctx(taxonomy_code="b")) is True
    assert _rule_matches(rule, _ctx(taxonomy_code="d")) is False
    # Empty array treated as "any" — defensive though the API
    # converts `[]` → `None` before persisting.
    assert (
        _rule_matches(_rule(match_taxonomy_codes=[]), _ctx(taxonomy_code="x"))
        is True
    )


def test_rule_nps_score_max_inclusive_threshold() -> None:
    from imga_api.services.sla_engine import _rule_matches

    rule = _rule(match_nps_score_max=6)
    assert _rule_matches(rule, _ctx(nps_score=6)) is True
    assert _rule_matches(rule, _ctx(nps_score=5)) is True
    assert _rule_matches(rule, _ctx(nps_score=7)) is False
    # Missing NPS data + rule has the matcher → no false positive.
    assert _rule_matches(rule, _ctx(nps_score=None)) is False


def test_breach_severity_classification() -> None:
    from imga_api.services.sla_engine import _to_match

    response_only = _to_match(
        _rule(response_sla_minutes=60, resolution_sla_minutes=None)
    )
    resolution_only = _to_match(
        _rule(response_sla_minutes=None, resolution_sla_minutes=240)
    )
    both = _to_match(
        _rule(response_sla_minutes=60, resolution_sla_minutes=240)
    )
    assert response_only.breach_severity == "response"
    assert resolution_only.breach_severity == "resolution"
    assert both.breach_severity == "both"


def test_match_carries_action_type_and_config() -> None:
    from imga_api.services.sla_engine import _to_match

    rule = _rule(
        action_type="warn_only",
        action_config={"channel": "stdout"},
    )
    match = _to_match(rule)
    assert match.action_type == "warn_only"
    assert match.action_config == {"channel": "stdout"}


# --- execute_action wiring ------------------------------------------------


@pytest.mark.asyncio
async def test_execute_action_warn_only_is_noop() -> None:
    from imga_api.services.sla_engine import _to_match

    match = _to_match(_rule(action_type="warn_only"))
    # Must not raise.
    await execute_action(match)


@pytest.mark.asyncio
async def test_execute_action_unwired_actions_raise_not_implemented() -> None:
    """create_ticket / escalate / notify_email all raise until the
    sprints that wire them. Tenants can already configure these
    rules; activation is the part that's deferred."""
    from imga_api.services.sla_engine import _to_match

    for action in ("create_ticket", "escalate", "notify_email"):
        match = _to_match(_rule(action_type=action))
        with pytest.raises(NotImplementedError):
            await execute_action(match)


