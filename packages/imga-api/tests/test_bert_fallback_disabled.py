"""2026-08-10 — IMGA_BATCH_BERT_FALLBACK=false sozlesmesi.

Kullanici karari: sistem BERT'e hic dusmesin. Bayrak kapaliyken
(1) LLM baglami kurulamayan is bastan net gerekceyle failed olur,
(2) birlesik yol chunk'ta kalici cokerse is chunk-basi satir-failed
gecidine girmeden durdurulur. Varsayilan (bayrak acik) davranis
suitin geri kalaninca zaten sabitlenmistir.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import AnalyzeBatchJob, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.workers import batch_analyzer
from tests.batch_helpers import login_token, run_worker, upload_csv, write_csv


async def _job_row(
    admin_session: AsyncSession, tenant_id: UUID
) -> AnalyzeBatchJob:
    async with admin_session.begin():
        stmt = (
            select(AnalyzeBatchJob)
            .where(AnalyzeBatchJob.tenant_id == tenant_id)
            .order_by(AnalyzeBatchJob.created_at.desc())
            .limit(1)
        )
        row = (await admin_session.execute(stmt)).scalar_one()
        admin_session.expunge(row)
        return row


def _upload(
    batch_client: TestClient, tmp_path: Path, user: User, tenant_id: UUID, pw: str
) -> UUID:
    token = login_token(batch_client, user.email, pw, tenant_id)
    path = write_csv(
        tmp_path / "mini.csv",
        ["yorum"],
        [["Kargom gelmedi cok magdurum"], ["Tesekkurler harika hizmet"]],
    )
    r = upload_csv(batch_client, token=token, path=path, text_column="yorum")
    assert r.status_code == 201, r.text
    return UUID(r.json()["job_id"])


@pytest.mark.asyncio
async def test_no_credentials_fails_job_fast_when_fallback_disabled(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user, tid, pw = semi_auto_tenant
    monkeypatch.setenv("IMGA_BATCH_BERT_FALLBACK", "false")

    job_id = _upload(batch_client, tmp_path, user, tid, pw)
    await run_worker(batch_client, job_id)

    job = await _job_row(admin_session, tid)
    assert job.status == "failed"
    assert job.last_error is not None
    assert "BERT" in job.last_error
    assert job.processed_rows == 0


@pytest.mark.asyncio
async def test_unified_chunk_failure_stops_job_when_fallback_disabled(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user, tid, pw = semi_auto_tenant
    monkeypatch.setenv("IMGA_BATCH_BERT_FALLBACK", "false")
    await mock_gemini_credential(tid, "fake-key-for-unified-path-123")

    async def _boom(self, texts, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("unified permanently down (test)")

    from imga_core.pipeline import AnalysisPipeline

    monkeypatch.setattr(
        AnalysisPipeline, "analyze_batch_unified_async", _boom
    )

    job_id = _upload(batch_client, tmp_path, user, tid, pw)
    await run_worker(batch_client, job_id)

    job = await _job_row(admin_session, tid)
    assert job.status == "failed"
    assert job.last_error is not None
    assert "IMGA_BATCH_BERT_FALLBACK" in job.last_error


def test_fallback_flag_default_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IMGA_BATCH_BERT_FALLBACK", raising=False)
    assert batch_analyzer._bert_fallback_enabled() is True
    monkeypatch.setenv("IMGA_BATCH_BERT_FALLBACK", "false")
    assert batch_analyzer._bert_fallback_enabled() is False
