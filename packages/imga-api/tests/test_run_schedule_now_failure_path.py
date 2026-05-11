"""Sprint 9.4.2 hotfix — run-now failure-path contract regression.

The route at ``POST /tenants/me/briefing-schedules/{id}/run-now``
catches a failed ``ExecutiveBriefingService.generate(...)``,
records ``last_run_status='failed'`` + ``last_run_error=...`` on
the schedule, and returns 200 with the updated schedule.

This is the contract the Sprint 9.4.2 C frontend fix relies on:
the toast inspects ``response.last_run_status`` instead of
treating HTTP 200 as success. If a future refactor removes the
try/except and lets the exception escape, the route would 500
and the frontend's `onSuccess` would never run — the operator
would see a stack-trace toast instead of "Brifing üretilemedi:
..." with the actual error.

This test pins the catch + 200 + ``last_run_status='failed'``
shape so that refactor surfaces here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import BriefingSchedule, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services import executive_briefing_service as ebs_module
from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_run_now_briefing_failure_returns_200_with_failed_status(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant

    # Seed a schedule directly so we don't depend on the create
    # endpoint's validation rules in this test.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        schedule = BriefingSchedule(
            tenant_id=tid,
            period="monthly",
            schedule_day=1,
            schedule_hour=9,
            timezone="Europe/Istanbul",
            recipients=[],
            email_recipients=[],
            enabled=True,
            next_run_at=datetime.now(UTC) + timedelta(days=30),
        )
        admin_session.add(schedule)
        await admin_session.flush()
        schedule_id = schedule.id

    # Force the briefing service to raise — mirrors a Gemini 504 or
    # any other provider failure path the route handler must catch.
    async def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Gemini API call failed: 504 Deadline Exceeded")

    monkeypatch.setattr(
        ebs_module.ExecutiveBriefingService, "generate", _fail,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        f"/tenants/me/briefing-schedules/{schedule_id}/run-now",
        headers={"Authorization": f"Bearer {token}"},
    )

    # 200 — the route catches the failure rather than 500-ing.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_run_status"] == "failed"
    assert body["last_run_at"] is not None
    assert body["last_run_briefing_id"] is None
    assert "504" in (body["last_run_error"] or ""), (
        f"last_run_error must surface the underlying provider failure; "
        f"got {body['last_run_error']!r}"
    )

    # DB row mirrors the response.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        stored = (
            await admin_session.execute(
                select(BriefingSchedule).where(
                    BriefingSchedule.id == schedule_id
                )
            )
        ).scalar_one()
        assert stored.last_run_status == "failed"
        assert stored.last_run_error is not None
        assert "504" in stored.last_run_error
