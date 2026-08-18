"""2026-08-18 (migration 0042) "büyük paket" WS2 — kalite raporu
endpoint'leri: ``GET /tenants/me/analyze/batch/{job_id}/quality-report``
+ ``POST .../quality-report/generate``.

Requires live Postgres; server test-compose suite.

Katmanlar (test_root_cause.py'nin ayrımıyla aynı):
  * Servis: sağlayıcı enjekte edilir (``QualityReportService(provider=)``).
    Gerçek LLM çağrısı YOK.
  * Rota: hata haritası + rol kapısı ``QualityReportService.generate_summary``
    monkeypatch'lenerek doğrulanır.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import BatchJobStatus, User, UserTenantRole
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services import AuditService, BatchAnalyzeService, UserService
from imga_api.services.llm_credentials import NoCredentialsError
from tests.batch_helpers import fetch_job, login_token, run_worker, upload_csv, write_csv


async def _bind(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        sa_text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )


async def _seed_completed_job(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    triggered_by_user_id: UUID,
    quality_meaningless_rows: int = 0,
) -> UUID:
    """Minimal COMPLETED job row via the real service (picks up every
    NOT NULL default correctly) — no file, no worker run needed since
    QualityReportService only reads job columns + reviews rows."""
    async with admin_session.begin():
        await _bind(admin_session, tenant_id)
        audit = AuditService(admin_session)
        service = BatchAnalyzeService(admin_session, audit)
        job = await service.create_job(
            tenant_id=tenant_id,
            triggered_by_user_id=triggered_by_user_id,
            file_name="quality.csv",
            file_size_bytes=10,
            file_path="/tmp/quality.csv",
            text_column="yorum",
            source_column=None,
            auto_create_tickets=False,
            total_rows=1,
        )
        job.status = BatchJobStatus.COMPLETED
        job.processed_rows = 1
        job.succeeded_rows = 1
        job.quality_meaningless_rows = quality_meaningless_rows
        job_id = job.id
        await admin_session.flush()
    return job_id


_GET_ENDPOINT = "/tenants/me/analyze/batch/{job_id}/quality-report"
_POST_ENDPOINT = "/tenants/me/analyze/batch/{job_id}/quality-report/generate"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assessment_payload() -> dict[str, Any]:
    return {"assessment": "Kopya oranı yüksek; şablon kalıpları filtrelenmeli."}


def _build_mock_provider(
    *, side_effect: Exception | None = None
) -> Any:
    """``generate_root_cause`` — QualityReportService'in dokunduğu tek
    attribute (bkz. batch_service.py'deki vekil kullanımı gerekçesi)."""
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    if side_effect is not None:
        provider.generate_root_cause = AsyncMock(  # type: ignore[method-assign]
            side_effect=side_effect
        )
    else:
        provider.generate_root_cause = AsyncMock(  # type: ignore[method-assign]
            return_value=(_assessment_payload(), {"input": 80, "output": 40})
        )
    return provider


async def _upload_and_run(
    batch_client: TestClient,
    *,
    token: str,
    tmp_path: Path,
    rows: list[list[str]],
    filename: str = "quality.csv",
    auto_create_tickets: bool = False,
) -> UUID:
    csv_path = write_csv(tmp_path / filename, ["yorum"], rows)
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=auto_create_tickets,
    )
    assert r.status_code == 201, r.text
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)
    return job_id


# ---------------------------------------------------------------------------
# GET — read path (no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_quality_report_returns_counters(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    job_id = await _upload_and_run(
        batch_client,
        token=token,
        tmp_path=tmp_path,
        rows=[
            ["tekrarlanan içerik burada"],
            ["tekrarlanan içerik burada"],
            [""],
            ["Tamam"],
        ],
    )
    job = await fetch_job(admin_session, job_id)

    r = batch_client.get(
        _GET_ENDPOINT.format(job_id=job_id), headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == str(job_id)
    assert body["counts"]["duplicate"] == job.quality_duplicate_rows == 1
    assert body["counts"]["empty"] == job.quality_empty_rows == 1
    assert body["counts"]["meaningless"] == job.quality_meaningless_rows == 1
    assert body["summary"] is None  # never generated


@pytest.mark.asyncio
async def test_get_quality_report_top_repeated_texts(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    repeated = "bu metin dosyada üç kez geçiyor"
    job_id = await _upload_and_run(
        batch_client,
        token=token,
        tmp_path=tmp_path,
        rows=[[repeated], [repeated], [repeated], ["farklı tek metin"]],
    )

    r = batch_client.get(
        _GET_ENDPOINT.format(job_id=job_id), headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    top = r.json()["top_repeated_texts"]
    assert len(top) == 1
    assert top[0]["count"] == 3
    assert top[0]["sample_text"] == repeated


@pytest.mark.asyncio
async def test_get_quality_report_entered_by_breakdown(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    from imga_db.models import TenantBusinessDimension

    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    async with admin_session.begin():
        admin_session.add(
            TenantBusinessDimension(
                tenant_id=tid,
                dimension="entered_by",
                display_label="Çalışan",
                enabled=True,
                allowed_values=[],
                csv_column_mapping="calisan",
            )
        )

    csv_path = tmp_path / "with_employee.csv"
    write_csv(
        csv_path,
        ["yorum", "calisan"],
        [
            ["ürünle ilgili birinci genel yorum metni", "Ahmet Yılmaz"],
            ["ürünle ilgili ikinci genel yorum metni", "Ahmet Yılmaz"],
            ["", ""],
        ],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    r = batch_client.get(
        _GET_ENDPOINT.format(job_id=job_id), headers=_auth(token)
    )
    assert r.status_code == 200, r.text
    breakdown = {
        row["entered_by"]: row for row in r.json()["entered_by_breakdown"]
    }
    assert breakdown["Ahmet Yılmaz"]["total"] == 2
    # Boş satır entered_by mapping'i olmayan bir hücreden geldiği için
    # None grubuna düşer.
    assert breakdown[None]["total"] == 1
    assert breakdown[None]["empty"] == 1


@pytest.mark.asyncio
async def test_get_quality_report_404_unknown_job(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        _GET_ENDPOINT.format(job_id=uuid4()), headers=_auth(token)
    )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# POST — LLM summary generation (service-level, injected provider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_summary_persists_and_caches(
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    from imga_api.services.batch_service import QualityReportService

    user, tid, _pw = manual_tenant
    await mock_gemini_credential(tid, "fake-key", priority=0)
    job_id = await _seed_completed_job(
        admin_session,
        tenant_id=tid,
        triggered_by_user_id=user.id,
        quality_meaningless_rows=1,
    )

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind(admin_session, tid)
        audit = AuditService(admin_session)
        job = await BatchAnalyzeService(admin_session, audit).get_job(job_id)

        service = QualityReportService(admin_session, provider=provider)
        result = await service.generate_summary(job, tenant_id=tid)
        assert result["summary"]["assessment"] == (
            _assessment_payload()["assessment"]
        )
        assert provider.generate_root_cause.await_count == 1

        # İkinci çağrı — cache dolu, LLM'e hiç dokunmamalı.
        result2 = await service.generate_summary(job, tenant_id=tid)
        assert result2["summary"]["assessment"] == (
            _assessment_payload()["assessment"]
        )
        assert provider.generate_root_cause.await_count == 1

        assert job.quality_summary is not None
        assert job.quality_summary["assessment"] == (
            _assessment_payload()["assessment"]
        )


@pytest.mark.asyncio
async def test_generate_summary_raises_without_credentials(
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    from imga_api.services.batch_service import QualityReportService

    user, tid, _pw = manual_tenant
    job_id = await _seed_completed_job(
        admin_session, tenant_id=tid, triggered_by_user_id=user.id
    )

    async with admin_session.begin():
        await _bind(admin_session, tid)
        audit = AuditService(admin_session)
        job = await BatchAnalyzeService(admin_session, audit).get_job(job_id)

        service = QualityReportService(admin_session)
        with pytest.raises(NoCredentialsError):
            await service.generate_summary(job, tenant_id=tid)


# ---------------------------------------------------------------------------
# POST — route-level error mapping + role gate (monkeypatched service)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_generate_without_credentials_returns_412(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)
    job_id = await _upload_and_run(
        batch_client, token=token, tmp_path=tmp_path, rows=[["tek satır burada"]]
    )

    from imga_api.services import batch_service

    monkeypatch.setattr(
        batch_service.QualityReportService,
        "generate_summary",
        AsyncMock(side_effect=NoCredentialsError("no keys")),
    )
    r = batch_client.post(
        _POST_ENDPOINT.format(job_id=job_id), headers=_auth(token)
    )
    assert r.status_code == 412, r.text


@pytest.mark.asyncio
async def test_post_generate_viewer_forbidden_analyst_allowed(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Okuma her üyeye açık; ÜRETİM yalnız yönetici + analist."""
    _admin, tid, pw = manual_tenant
    admin_token = login_token(batch_client, _admin.email, pw, tid)
    job_id = await _upload_and_run(
        batch_client,
        token=admin_token,
        tmp_path=tmp_path,
        rows=[["tek satır burada da"]],
    )

    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    viewer_pw = "Viewer-Password-123!"
    viewer_email = f"viewer-{uuid4().hex[:8]}@example.com"
    analyst_pw = "Analyst-Password-123!"
    analyst_email = f"analyst-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        viewer = await usvc.create(
            email=viewer_email, password=viewer_pw, full_name="QR Viewer"
        )
        await usvc.attach_to_tenant(
            user_id=viewer.id, tenant_id=tid, role=UserTenantRole.VIEWER
        )
        analyst = await usvc.create(
            email=analyst_email, password=analyst_pw, full_name="QR Analyst"
        )
        await usvc.attach_to_tenant(
            user_id=analyst.id, tenant_id=tid, role=UserTenantRole.ANALYST
        )
        viewer_id, analyst_id = viewer.id, analyst.id

    try:
        # Okuma viewer'a açık.
        viewer_token = login_token(batch_client, viewer_email, viewer_pw, tid)
        r = batch_client.get(
            _GET_ENDPOINT.format(job_id=job_id), headers=_auth(viewer_token)
        )
        assert r.status_code == 200, r.text

        # Üretim (POST) viewer'a kapalı.
        r = batch_client.post(
            _POST_ENDPOINT.format(job_id=job_id), headers=_auth(viewer_token)
        )
        assert r.status_code == 403, r.text

        from imga_api.services import batch_service

        monkeypatch.setattr(
            batch_service.QualityReportService,
            "generate_summary",
            AsyncMock(
                return_value={
                    "job_id": str(job_id),
                    "total_rows": 1,
                    "succeeded_rows": 1,
                    "counts": {
                        "duplicate": 0,
                        "empty": 0,
                        "informational": 0,
                        "meaningless": 0,
                    },
                    "top_repeated_texts": [],
                    "entered_by_breakdown": [],
                    "summary": {
                        "assessment": "test",
                        "model_provider": "gemini",
                        "model_name": "gemini-3-flash-preview",
                        "generated_at": "2026-08-18T00:00:00+00:00",
                    },
                }
            ),
        )
        analyst_token = login_token(
            batch_client, analyst_email, analyst_pw, tid
        )
        r = batch_client.post(
            _POST_ENDPOINT.format(job_id=job_id), headers=_auth(analyst_token)
        )
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["assessment"] == "test"
    finally:
        async with admin_session.begin():
            await admin_session.execute(
                sa_text("DELETE FROM users WHERE id = ANY(:ids)"),
                {"ids": [str(viewer_id), str(analyst_id)]},
            )
