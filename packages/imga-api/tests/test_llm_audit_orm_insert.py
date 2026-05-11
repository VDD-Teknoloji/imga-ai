"""Sprint 9.4.2 hotfix — LlmCallAudit ORM Computed-column regression.

Migration 0027 declared ``llm_call_audit.total_tokens`` as
``GENERATED ALWAYS AS (COALESCE(input_tokens, 0) +
COALESCE(output_tokens, 0)) STORED``. The ORM model originally
declared the same column as a plain ``mapped_column(Integer())``
without the ``Computed`` flag, so SQLAlchemy's INSERT statement
included ``total_tokens=NULL`` in the column list. PostgreSQL
rejects that with ``GeneratedAlwaysError`` — and because Sprint
9.4 F wraps the audit insert in a SAVEPOINT, the failure was
silent: the savepoint rolled back, the main transaction kept
going, the briefing landed in prod, and the audit table stayed
empty for four hours.

This regression locks the fix: an ORM insert with ``input_tokens``
+ ``output_tokens`` set must succeed and the DB-computed
``total_tokens`` must be readable back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from imga_db.models import LlmCallAudit, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession


async def _bind(admin_session: AsyncSession, tenant_id: UUID) -> None:
    await admin_session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )


@pytest.mark.asyncio
async def test_orm_insert_succeeds_without_setting_total_tokens(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """The fix: SQLAlchemy's INSERT must omit ``total_tokens`` from the
    column list. Pre-fix the column was sent as NULL and Postgres
    raised ``GeneratedAlwaysError``."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind(admin_session, tid)
        row = LlmCallAudit(
            tenant_id=tid,
            call_type="briefing",
            prompt_hash="a" * 64,
            model_name="gemini-2.5-flash",
            model_provider="gemini",
            input_tokens=120,
            output_tokens=480,
            duration_ms=2300,
            success=True,
            fallback_used=False,
            created_at=datetime.now(UTC),
        )
        admin_session.add(row)
        await admin_session.flush()
        row_id = row.id

    # Re-read in a fresh transaction so the generated-always column
    # is loaded from disk (Postgres computes it at INSERT time).
    async with admin_session.begin():
        await _bind(admin_session, tid)
        stored = (
            await admin_session.execute(
                select(LlmCallAudit).where(LlmCallAudit.id == row_id)
            )
        ).scalar_one()
        assert stored.input_tokens == 120
        assert stored.output_tokens == 480
        # Computed by Postgres — never set by Python.
        assert stored.total_tokens == 600


@pytest.mark.asyncio
async def test_orm_insert_handles_null_token_inputs(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """A failed LLM call (no usage_metadata returned) lands with
    NULL input/output tokens. The COALESCE in the generated
    expression must zero them — total_tokens=0, not NULL — so the
    summary endpoint's SUM doesn't have to special-case None."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind(admin_session, tid)
        row = LlmCallAudit(
            tenant_id=tid,
            call_type="briefing",
            prompt_hash="b" * 64,
            model_name="gemini-2.5-flash",
            model_provider="gemini",
            input_tokens=None,
            output_tokens=None,
            duration_ms=180,
            success=False,
            error_type="api_error",
            error_message="504 Deadline Exceeded",
            fallback_used=False,
            created_at=datetime.now(UTC),
        )
        admin_session.add(row)
        await admin_session.flush()
        row_id = row.id

    async with admin_session.begin():
        await _bind(admin_session, tid)
        stored = (
            await admin_session.execute(
                select(LlmCallAudit).where(LlmCallAudit.id == row_id)
            )
        ).scalar_one()
        assert stored.input_tokens is None
        assert stored.output_tokens is None
        assert stored.total_tokens == 0
