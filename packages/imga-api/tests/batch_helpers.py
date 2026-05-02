"""Helper functions + classes shared across the Sprint 8.3.1 batch
test suite. Fixtures live in ``conftest.py``; this module only holds
plain helpers (no @pytest.fixture decorators) to keep ruff's F811
duplicate-fixture detection happy.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from imga_core import (
    AnalyzerPrediction,
    SentimentAnalyzer,
)
from imga_db.models import (
    AnalyzeBatchJob,
    AutomationMode,
    Tenant,
    User,
    UserTenantRole,
)
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services import AuditService, TenantService, UserService
from imga_api.workers import batch_analyzer
from imga_api.workers.batch_analyzer import WorkerContext

# --- stub pipeline ---------------------------------------------------


class StubBatchAnalyzer(SentimentAnalyzer):
    """Deterministic sentiment used by the batch fixture: 'kötü' /
    'gelmedi' / 'berbat' → NEGATIF, 'iyi' / 'güzel' / 'harika' →
    POZITIF, else NÖTR. No async hook — the worker's per-chunk DB
    commit serves as the natural yield point in concurrency tests."""

    def analyze_batch(self, texts: list[str]) -> list[AnalyzerPrediction]:
        from imga_core.text_utils import normalize_turkish

        out: list[AnalyzerPrediction] = []
        for raw in texts:
            t = normalize_turkish(raw)
            if any(w in t for w in ("kötü", "gelmedi", "berbat")):
                out.append(AnalyzerPrediction(label="NEGATIF", score=-0.85))
            elif any(w in t for w in ("iyi", "güzel", "harika")):
                out.append(AnalyzerPrediction(label="POZITIF", score=0.85))
            else:
                out.append(AnalyzerPrediction(label="NÖTR", score=0.0))
        return out


# --- no-op scheduler --------------------------------------------------


class RecordingScheduler:
    """Stand-in for AsyncIOScheduler in tests. Records add_job calls so
    a test can assert dispatch happened, but never actually fires the
    coroutine — tests drive the worker by directly awaiting
    ``process_batch_job`` for determinism."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    def add_job(self, *args: Any, **kwargs: Any) -> None:
        self.added.append({"args": args, "kwargs": kwargs})

    def remove_job(self, _job_id: str) -> None:
        return None

    def start(self) -> None:
        return None

    def shutdown(self, **_kwargs: Any) -> None:
        return None


# --- DB seeding -------------------------------------------------------


def login_token(
    client: TestClient, email: str, password: str, tenant_id: UUID
) -> str:
    r = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": password,
            "active_tenant_id": str(tenant_id),
        },
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


async def seed_tenant_with_admin(
    admin_session: AsyncSession,
    *,
    automation_mode: AutomationMode = AutomationMode.SEMI_AUTO,
    name_prefix: str = "Batch Co",
) -> tuple[User, UUID, str]:
    audit = AuditService(admin_session)
    tsvc = TenantService(admin_session, audit)
    usvc = UserService(admin_session, audit)
    plain = "Test-Password-123!"
    email = f"batch-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        tenant = await tsvc.create(
            name=name_prefix, slug=f"batch-{uuid4().hex[:8]}"
        )
        tenant_obj = await admin_session.get(Tenant, tenant.id)
        assert tenant_obj is not None
        tenant_obj.automation_mode = automation_mode

        user = await usvc.create(email=email, password=plain, full_name="Batch User")
        await usvc.attach_to_tenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserTenantRole.TENANT_ADMIN,
        )
        return user, tenant.id, plain


async def cleanup_tenant(
    admin_session: AsyncSession, user_id: UUID, tenant_id: UUID
) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM reviews WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM ticket_state_transitions WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM tickets WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM analyze_batch_jobs WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)}
        )
        await admin_session.execute(
            text("DELETE FROM tenants WHERE id = :id"), {"id": str(tenant_id)}
        )


# --- file makers ----------------------------------------------------


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_xlsx(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


# --- worker driver --------------------------------------------------


async def run_worker(client: TestClient, job_id: UUID) -> None:
    """Directly drive ``process_batch_job`` against the test app's
    worker context. Use this immediately after POST /...batch when
    the test wants the worker run to completion (the lifespan replaced
    the real scheduler with a no-op; nothing fires automatically)."""
    context: WorkerContext = client.app.state.batch_worker_context  # type: ignore[attr-defined]
    await batch_analyzer.process_batch_job(job_id, context)


async def fetch_job(
    admin_session: AsyncSession, job_id: UUID
) -> AnalyzeBatchJob:
    async with admin_session.begin():
        job = await admin_session.get(AnalyzeBatchJob, job_id)
        assert job is not None
        admin_session.expunge(job)
    return job


def upload_csv(
    client: TestClient,
    *,
    token: str,
    path: Path,
    text_column: str = "text",
    source_column: str | None = None,
    auto_create_tickets: bool = False,
) -> Any:
    """Multipart POST helper. Returns the requests Response object."""
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, "text/csv")}
        data: dict[str, str] = {
            "text_column": text_column,
            "auto_create_tickets": "true" if auto_create_tickets else "false",
        }
        if source_column:
            data["source_column"] = source_column
        return client.post(
            "/tenants/me/analyze/batch",
            headers={"Authorization": f"Bearer {token}"},
            files=files,
            data=data,
        )
