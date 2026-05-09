"""Sprint 9.4 F — LLM audit savepoint isolation regression tests.

Pre-9.4 ``_insert_row`` ran the audit ``session.add()`` + ``flush()``
directly on the request's main transaction. Any flush failure
(integrity violation, FK miss, etc.) left the entire transaction
in a failed state — the briefing or strategic-report row that
the call site was about to commit would then 500 on the second
flush even though the original LLM call succeeded.

The fix wraps the audit insert in ``begin_nested()`` (SAVEPOINT).
This test pins the contract: when the audit insert raises, only
the savepoint rolls back. Subsequent work on the outer session
must continue cleanly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from imga_api.services.llm_audit_service import (
    LLMCallAuditor,
    LLMCallContext,
)


def _build_session_with_savepoint_capture() -> tuple[Any, list[str]]:
    """Build a fake AsyncSession that records savepoint lifecycle
    events to a list — entered, committed, rolled back. Lets us
    assert the auditor opened a SAVEPOINT (not the outer
    transaction) for its insert."""
    events: list[str] = []
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    class _SavepointCtx:
        async def __aenter__(self) -> Any:
            events.append("savepoint_enter")
            return self

        async def __aexit__(
            self, exc_type: Any, exc_val: Any, exc_tb: Any
        ) -> bool:
            if exc_type is None:
                events.append("savepoint_commit")
            else:
                events.append("savepoint_rollback")
            # Returning False (default) lets the exception propagate
            # OUT of the savepoint — but the auditor catches it.
            return False

    session.begin_nested = MagicMock(side_effect=lambda: _SavepointCtx())
    return session, events


@pytest.mark.asyncio
async def test_audit_insert_uses_savepoint_on_success() -> None:
    """Happy path: insert lands inside a SAVEPOINT block. The
    auditor never touches the outer transaction directly."""
    session, events = _build_session_with_savepoint_capture()
    ctx = LLMCallContext(
        tenant_id=uuid4(),
        call_type="briefing",
        model_name="gemini-2.5-flash",
    )
    auditor = LLMCallAuditor(session, ctx, prompt="merhaba")

    async with auditor:
        auditor.record_success(input_tokens=10, output_tokens=5)

    assert events == ["savepoint_enter", "savepoint_commit"]
    session.add.assert_called_once()
    session.flush.assert_awaited()


@pytest.mark.asyncio
async def test_audit_insert_failure_rolls_back_savepoint_only() -> None:
    """Failure path: ``session.flush()`` raises an integrity error.
    The auditor must catch it after the savepoint rollback so the
    outer transaction is unaffected."""
    session, events = _build_session_with_savepoint_capture()
    session.flush.side_effect = RuntimeError(
        "duplicate key value violates unique constraint"
    )
    ctx = LLMCallContext(
        tenant_id=uuid4(),
        call_type="briefing",
        model_name="gemini-2.5-flash",
    )
    auditor = LLMCallAuditor(session, ctx, prompt="merhaba")

    # No exception escapes the auditor — best-effort by contract.
    async with auditor:
        auditor.record_success()

    assert "savepoint_enter" in events
    assert "savepoint_rollback" in events
    # The auditor logs + swallows; outer caller can keep working.


@pytest.mark.asyncio
async def test_audit_insert_failure_does_not_propagate_to_caller() -> None:
    """End-to-end contract: the call site doesn't see audit
    failures. ``async with auditor:`` exits cleanly even when the
    insert blows up — preserving "auditing is observability, not
    primary contract"."""
    session, _ = _build_session_with_savepoint_capture()
    session.flush.side_effect = RuntimeError("boom")
    ctx = LLMCallContext(
        tenant_id=uuid4(),
        call_type="briefing",
        model_name="gemini-2.5-flash",
    )

    # Should NOT raise.
    async with LLMCallAuditor(session, ctx, prompt="x") as auditor:
        auditor.record_success()
