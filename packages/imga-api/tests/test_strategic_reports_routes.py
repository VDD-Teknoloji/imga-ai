"""Sprint 8.3.6.5 — strategic-reports route tests.

Route layer focus: error mapping + RLS behaviour + PDF Content-Type.
The service-level SWOT/OKR generation paths already have deep
coverage in test_swot_service.py / test_okr_service.py — these tests
verify the HTTP wrapper, not the underlying generators.

Pattern:
  * SwotService.generate / OkrService.generate are monkeypatched per
    test with AsyncMock returns or side_effects so we drive the
    happy + sad paths without burning Gemini calls.
  * For success cases that need ``app_session.get(StrategicReport,
    id)`` to resolve, we pre-insert a real row and feed the mock to
    return its id. Route handler reads it back and surfaces the
    detail response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core.llm.errors import AllKeysExhaustedError
from imga_db.models import StrategicReport, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.okr_service import SourceReportNotFoundError

from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)


def _swot_payload() -> dict[str, Any]:
    item = {"title": "X", "description": "Y", "evidence": "Z"}
    rec = {
        "title": "A",
        "description": "B",
        "priority": "yüksek",
        "estimated_impact": "orta",
    }
    return {
        "strengths": [item, item],
        "weaknesses": [item, item],
        "opportunities": [item, item],
        "threats": [item, item],
        "strategic_recommendations": [rec, rec, rec],
    }


def _okr_payload() -> dict[str, Any]:
    kr = {"text": "X", "metric": "Y", "baseline": "0", "target": "10"}
    return {
        "objectives": [
            {"objective": "Obj", "rationale": "R", "key_results": [kr, kr]},
            {"objective": "Obj2", "rationale": "R2", "key_results": [kr, kr]},
        ]
    }


async def _seed_report(
    admin_session: AsyncSession,
    tenant_id: UUID,
    *,
    report_type: str = "swot",
    output_payload: dict[str, Any] | None = None,
    source_report_id: UUID | None = None,
) -> UUID:
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        row = StrategicReport(
            tenant_id=tenant_id,
            report_type=report_type,
            input_stats={"total_reviews": 100, "stats_hash": "abc"},
            output_payload=output_payload
            or (_swot_payload() if report_type == "swot" else _okr_payload()),
            source_report_id=source_report_id,
            model_name="gemini-2.5-pro",
            generation_duration_ms=42,
        )
        admin_session.add(row)
        await admin_session.flush()
        rid = row.id
        admin_session.expunge(row)
    return rid


# ---------------------------------------------------------------------------
# POST /swot/generate — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_swot_no_credentials_returns_503(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NoCredentialsError → 503 + ``no_llm_credentials`` code so the
    frontend can redirect to /settings/integrations."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    from imga_api.services import swot_service

    monkeypatch.setattr(
        swot_service.SwotService,
        "generate",
        AsyncMock(side_effect=NoCredentialsError("no keys")),
    )

    r = batch_client.post(
        "/tenants/me/strategic-reports/swot/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["detail"]["code"] == "no_llm_credentials"


@pytest.mark.asyncio
async def test_generate_swot_all_keys_exhausted_returns_503(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    from imga_api.services import swot_service

    monkeypatch.setattr(
        swot_service.SwotService,
        "generate",
        AsyncMock(side_effect=AllKeysExhaustedError("all keys failed")),
    )

    r = batch_client.post(
        "/tenants/me/strategic-reports/swot/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "all_keys_exhausted"


@pytest.mark.asyncio
async def test_generate_swot_happy_path_returns_201_with_detail(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service generate returns the persisted row's serialised dict;
    route handler reloads the row + responds 201 + detail."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # Pre-seed a real DB row so the route's app_session.get resolves.
    rid = await _seed_report(admin_session, tid, report_type="swot")

    from imga_api.services import swot_service

    async def _fake_generate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"id": str(rid), "report_type": "swot"}

    monkeypatch.setattr(
        swot_service.SwotService, "generate", _fake_generate
    )

    r = batch_client.post(
        "/tenants/me/strategic-reports/swot/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert UUID(body["id"]) == rid
    assert body["report_type"] == "swot"
    assert "output_payload" in body
    assert "input_stats" in body


# ---------------------------------------------------------------------------
# POST /okr/generate — happy + 404 source-not-found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_okr_happy_path_returns_201(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    swot_id = await _seed_report(admin_session, tid, report_type="swot")
    okr_id = await _seed_report(
        admin_session, tid, report_type="okr", source_report_id=swot_id
    )

    from imga_api.services import okr_service

    async def _fake_generate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"id": str(okr_id), "report_type": "okr"}

    monkeypatch.setattr(
        okr_service.OkrService, "generate", _fake_generate
    )

    r = batch_client.post(
        "/tenants/me/strategic-reports/okr/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_report_id": str(swot_id)},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert UUID(body["id"]) == okr_id
    assert UUID(body["source_report_id"]) == swot_id


@pytest.mark.asyncio
async def test_generate_okr_invalid_source_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    from imga_api.services import okr_service

    monkeypatch.setattr(
        okr_service.OkrService,
        "generate",
        AsyncMock(side_effect=SourceReportNotFoundError("not found")),
    )

    r = batch_client.post(
        "/tenants/me/strategic-reports/okr/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"source_report_id": str(uuid4())},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET / + GET /{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reports_with_type_filter(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    swot_id = await _seed_report(admin_session, tid, report_type="swot")
    await _seed_report(
        admin_session, tid, report_type="okr", source_report_id=swot_id
    )

    r_all = batch_client.get(
        "/tenants/me/strategic-reports",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_all.status_code == 200
    assert r_all.json()["total"] == 2

    r_swot = batch_client.get(
        "/tenants/me/strategic-reports?report_type=swot",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_swot.status_code == 200
    body_swot = r_swot.json()
    assert body_swot["total"] == 1
    assert all(it["report_type"] == "swot" for it in body_swot["items"])


@pytest.mark.asyncio
async def test_get_report_other_tenant_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenant B can't fetch tenant A's strategic report — RLS hides it."""
    user_a, tid_a, _pw_a = semi_auto_tenant
    rid_a = await _seed_report(admin_session, tid_a, report_type="swot")
    del user_a

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Strategic Other"
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            f"/tenants/me/strategic-reports/{rid_a}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)


# ---------------------------------------------------------------------------
# GET /{id}/download.pdf
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_pdf_returns_application_pdf(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Smoke: route returns 200 with application/pdf content-type and
    a body that starts with the PDF magic bytes."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    rid = await _seed_report(admin_session, tid, report_type="swot")

    r = batch_client.get(
        f"/tenants/me/strategic-reports/{rid}/download.pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    # Magic bytes — every valid PDF starts with %PDF-.
    assert r.content[:5] == b"%PDF-"
    assert "attachment" in r.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_pdf_other_tenant_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user_a, tid_a, _pw_a = semi_auto_tenant
    rid_a = await _seed_report(admin_session, tid_a, report_type="swot")
    del user_a

    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Strategic PDF Other"
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            f"/tenants/me/strategic-reports/{rid_a}/download.pdf",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)


# Silence unused imports if a future cleanup drops them.
_ = datetime
_ = UTC
