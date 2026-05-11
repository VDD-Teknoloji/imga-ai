"""Sprint 9.4.2 hotfix — /tenants/me/llm-audit/summary regression.

Pre-9.4.2 the summary endpoint ran two GROUP-BY queries (totals
vs failures) and joined them in Python. PostgreSQL rejected the
second one once real data landed in the table:

    column "llm_call_audit.created_at" must appear in the GROUP
    BY clause or be used in an aggregate function

The hotfix collapses the rollup into a single CASE-driven query
so the dual-statement subtlety is gone and the dashboard chart
renders against populated data.

Two scenarios:

  * Empty audit table — summary returns zeroed totals + empty
    days list. Pre-9.4.2 this case also worked (no rows = no
    GROUP BY exercised) so it's a contract pin, not a fix.
  * Populated table — three rows over two days, one of them a
    failure. Day rollup correctly partitions calls / failures /
    tokens, totals sum cleanly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import LlmCallAudit, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


async def _seed_audit_row(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    created_at: datetime,
    success: bool,
    input_tokens: int | None,
    output_tokens: int | None,
    call_type: str = "briefing",
) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        row = LlmCallAudit(
            tenant_id=tenant_id,
            call_type=call_type,
            prompt_hash="c" * 64,
            model_name="gemini-2.5-flash",
            model_provider="gemini",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=1000,
            success=success,
            error_type=None if success else "rate_limit",
            error_message=None if success else "429 too many requests",
            fallback_used=False,
            created_at=created_at,
        )
        admin_session.add(row)


@pytest.mark.asyncio
async def test_summary_endpoint_empty_table_returns_zero_totals(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/llm-audit/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_calls"] == 0
    assert body["total_failures"] == 0
    assert body["total_tokens"] == 0
    assert body["days"] == []


@pytest.mark.asyncio
async def test_summary_endpoint_populated_table_rolls_up_per_day(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Three rows across two days, one a failure. Verify the daily
    bucket math + totals."""
    user, tid, pw = semi_auto_tenant
    day_one = datetime.now(UTC) - timedelta(days=2)
    day_two = datetime.now(UTC) - timedelta(days=1)

    # Day one — one success (300 tokens).
    await _seed_audit_row(
        admin_session,
        tenant_id=tid,
        created_at=day_one,
        success=True,
        input_tokens=100,
        output_tokens=200,
    )
    # Day two — one success (600 tokens), one failure (no tokens).
    await _seed_audit_row(
        admin_session,
        tenant_id=tid,
        created_at=day_two,
        success=True,
        input_tokens=200,
        output_tokens=400,
    )
    await _seed_audit_row(
        admin_session,
        tenant_id=tid,
        created_at=day_two,
        success=False,
        input_tokens=None,
        output_tokens=None,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/llm-audit/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Totals — 3 calls, 1 failure, 900 tokens (300 + 600 + 0).
    assert body["total_calls"] == 3
    assert body["total_failures"] == 1
    assert body["total_tokens"] == 900

    # Two days in the bucket, ordered ascending.
    assert len(body["days"]) == 2
    d1, d2 = body["days"]
    assert d1["day"] == day_one.date().isoformat()
    assert d1["call_count"] == 1
    assert d1["success_count"] == 1
    assert d1["failure_count"] == 0
    assert d1["total_tokens"] == 300

    assert d2["day"] == day_two.date().isoformat()
    assert d2["call_count"] == 2
    assert d2["success_count"] == 1
    assert d2["failure_count"] == 1
    assert d2["total_tokens"] == 600
