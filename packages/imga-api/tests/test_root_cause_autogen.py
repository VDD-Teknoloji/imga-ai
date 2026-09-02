"""``services/root_cause_autogen.py`` — the Redis SET-based tracker
that replaced the single STRING flag ``root_cause_autogen:{tenant}``
(2026-09; see the module docstring for the full audit).

Pure-unit tests (fakeredis, no Postgres) cover the five helper
functions directly: set semantics, error-code set/clear, and the
legacy ``batch_job_id=None`` DEL-the-whole-set path. These run
anywhere.

One regression test at the bottom exercises the real worker task
(``arq_worker.generate_root_causes_task``) end-to-end against a live
``WorkerContext`` — same pattern as ``test_root_cause_overview.py``'s
auto-gen tests (``batch_client`` + ``semi_auto_tenant`` +
``admin_session``). It needs Postgres on :5433 and cannot run on a
machine without that; it is written and left here for CI / a
Postgres-backed run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import set_redis_client
from imga_api.services import root_cause_autogen

# ---------------------------------------------------------------------------
# Pure-unit fixtures/helpers — no DB, no TestClient event loop involved,
# so plain fakeredis (unlike test_root_cause_overview.py's loop-bound
# concern) is safe here.
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis() -> Any:
    import fakeredis.aioredis as fakeredis_async

    fake = fakeredis_async.FakeRedis(decode_responses=False)
    set_redis_client(fake)
    yield fake
    set_redis_client(None)


# ---------------------------------------------------------------------------
# mark_enqueued / mark_started / is_generating — set semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_generating_false_before_any_mark(fake_redis: Any) -> None:
    del fake_redis
    assert await root_cause_autogen.is_generating(uuid4()) is False


@pytest.mark.asyncio
async def test_mark_enqueued_makes_is_generating_true(fake_redis: Any) -> None:
    del fake_redis
    tid, job = uuid4(), uuid4()
    await root_cause_autogen.mark_enqueued(tid, job)
    assert await root_cause_autogen.is_generating(tid) is True


@pytest.mark.asyncio
async def test_mark_started_recreates_a_legacy_expired_membership(fake_redis: Any) -> None:
    """imga-batch tek işçili FIFO — büyük bir batch önde kuyrukta
    beklerken enqueue-anı üyeliğinin TTL'i işin gerçek başlangıcından
    ÖNCE dolabilir. mark_started sadece EXPIRE değil, SADD da yapar ki
    bu durumda üyelik sıfırdan yeniden kurulsun (mark_enqueued hiç
    çağrılmamış gibi davranarak simüle edilir)."""
    del fake_redis
    tid, job = uuid4(), uuid4()
    assert await root_cause_autogen.is_generating(tid) is False
    await root_cause_autogen.mark_started(tid, job)
    assert await root_cause_autogen.is_generating(tid) is True


@pytest.mark.asyncio
async def test_mark_finished_removes_only_its_own_batch_member(fake_redis: Any) -> None:
    """İki eşzamanlı yükleme aynı tenant için: birinin finally'si
    ötekinin hâlâ kuyrukta/işlemde olan job'unu SREM ETMEMELİ — eski
    tek-string bayrağın tam kırıldığı senaryo."""
    del fake_redis
    tid = uuid4()
    job_a, job_b = uuid4(), uuid4()
    await root_cause_autogen.mark_enqueued(tid, job_a)
    await root_cause_autogen.mark_enqueued(tid, job_b)
    assert await root_cause_autogen.is_generating(tid) is True

    await root_cause_autogen.mark_finished(tid, job_a, error=None)
    assert await root_cause_autogen.is_generating(tid) is True  # job_b hâlâ kuyrukta

    await root_cause_autogen.mark_finished(tid, job_b, error=None)
    assert await root_cause_autogen.is_generating(tid) is False


@pytest.mark.asyncio
async def test_mark_finished_none_batch_id_clears_whole_set(fake_redis: Any) -> None:
    """Legacy job (bu değişiklikten önce kuyruğa alınmış, ``batch_job_id``
    taşımıyor) — izleyecek kendi üyeliği hiç olmadığından SET'in
    TAMAMI silinir (SREM edilecek belirli bir üye yok)."""
    del fake_redis
    tid = uuid4()
    await root_cause_autogen.mark_enqueued(tid, uuid4())
    await root_cause_autogen.mark_enqueued(tid, uuid4())
    assert await root_cause_autogen.is_generating(tid) is True

    await root_cause_autogen.mark_finished(tid, None, error=None)
    assert await root_cause_autogen.is_generating(tid) is False


@pytest.mark.asyncio
async def test_is_generating_isolated_per_tenant(fake_redis: Any) -> None:
    del fake_redis
    tid_a, tid_b = uuid4(), uuid4()
    await root_cause_autogen.mark_enqueued(tid_a, uuid4())
    assert await root_cause_autogen.is_generating(tid_a) is True
    assert await root_cause_autogen.is_generating(tid_b) is False


# ---------------------------------------------------------------------------
# last_error — set / cleared / overwritten
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_error_none_before_any_run(fake_redis: Any) -> None:
    del fake_redis
    assert await root_cause_autogen.last_error(uuid4()) is None


@pytest.mark.asyncio
async def test_mark_finished_sets_and_clears_error(fake_redis: Any) -> None:
    del fake_redis
    tid = uuid4()
    await root_cause_autogen.mark_finished(tid, uuid4(), error="no_credentials")
    assert await root_cause_autogen.last_error(tid) == "no_credentials"

    await root_cause_autogen.mark_finished(tid, uuid4(), error=None)
    assert await root_cause_autogen.last_error(tid) is None


@pytest.mark.asyncio
async def test_mark_finished_error_overwritten_by_next_run(fake_redis: Any) -> None:
    del fake_redis
    tid = uuid4()
    await root_cause_autogen.mark_finished(tid, uuid4(), error="no_credentials")
    await root_cause_autogen.mark_finished(tid, uuid4(), error="failed")
    assert await root_cause_autogen.last_error(tid) == "failed"


# ---------------------------------------------------------------------------
# Redis failure defensiveness — never raises, readers default False/None
# ---------------------------------------------------------------------------


class _BoomRedis:
    """Every op raises — simulates Redis being unreachable/erroring."""

    async def sadd(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis down")

    async def srem(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis down")

    async def scard(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis down")

    async def expire(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("redis down")

    async def get(self, *args: Any, **kwargs: Any) -> bytes | None:
        raise ConnectionError("redis down")

    async def set(self, *args: Any, **kwargs: Any) -> bool:
        raise ConnectionError("redis down")

    async def delete(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_all_helpers_swallow_redis_failures() -> None:
    set_redis_client(_BoomRedis())
    try:
        tid, job = uuid4(), uuid4()
        # Writers: no exception propagates.
        await root_cause_autogen.mark_enqueued(tid, job)
        await root_cause_autogen.mark_started(tid, job)
        await root_cause_autogen.mark_finished(tid, job, error="failed")
        # Readers: defensive defaults.
        assert await root_cause_autogen.is_generating(tid) is False
        assert await root_cause_autogen.last_error(tid) is None
    finally:
        set_redis_client(None)


# ---------------------------------------------------------------------------
# Worker-task regression — real generate_root_causes_task against a
# live WorkerContext. Needs Postgres :5433 (same fixtures as
# test_root_cause_overview.py's auto-gen tests); cannot run on this
# machine, written per existing conventions for a Postgres-backed run.
# ---------------------------------------------------------------------------


async def _bind_tenant(session: AsyncSession, tid: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tid)},
    )


async def _seed_negative_reviews(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category: str,
    perspective_code: str,
    count: int,
) -> None:
    """Minimal local seeding helper (own copy — no cross-import with
    test_root_cause_overview.py, per that file's file-ownership-split
    convention). ``count`` NEGATIF reviews, all yesterday (comfortably
    inside both the rolling and day-rounded 90-day windows)."""
    when = datetime.now(UTC) - timedelta(days=1)
    for i in range(count):
        body = f"{category} negatif test yorumu {uuid4().hex[:8]} {i}"
        session.add(
            Review(
                tenant_id=tenant_id,
                text=body,
                text_hash=review_text_hash(body),
                sentiment_label="NEGATIF",
                sentiment_score=-0.8,
                primary_category=category,
                primary_confidence=0.9,
                automation_mode="semi_auto",
                decision=ReviewDecision.SKIPPED_THRESHOLD,
                decision_reason=None,
                ticket_id=None,
                submitted_by_user_id=None,
                analyzed_at=when,
                review_date=when,
                company_perspective_code=perspective_code,
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_worker_task_marks_no_credentials_on_generate_failure(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> None:
    """``RootCauseService.generate`` ``NoCredentialsError`` fırlatınca
    (kurumda aktif LLM anahtarı yok) ``generate_root_causes_task``
    KENDİ ``finally``'sinde ``mark_finished(..., error="no_credentials")``
    çağırmalı — task hâlâ ASLA raise etmez ("hata loglanır + yutulur"
    sözleşmesi korunur), ama artık hata Redis'e görünür biçimde
    yazılır (eski TTL-string tasarımı bunu sessizce kaybediyordu)."""
    del fake_redis
    from imga_api.services import root_cause_service
    from imga_api.services.llm_credentials import NoCredentialsError
    from imga_api.workers import arq_worker, batch_analyzer

    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        # Tek kategori, tenant eşiğini (50) ve kova eşiğini (10) aşan
        # tek bir aday üretir — sonuç deterministik biçimde bu TEK
        # kategorinin başarısızlığına bağlı.
        await _seed_negative_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=60,
        )

    mock_generate = AsyncMock(
        side_effect=NoCredentialsError("Tenant has no active LLM API keys configured")
    )
    monkeypatch.setattr(root_cause_service.RootCauseService, "generate", mock_generate)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    batch_job_id = uuid4()
    try:
        await arq_worker.generate_root_causes_task(
            {"worker_context": context},
            str(tid),
            rows_succeeded=60,
            batch_job_id=str(batch_job_id),
        )
    finally:
        await context.dispose()

    mock_generate.assert_awaited()
    assert await root_cause_autogen.last_error(tid) == "no_credentials"
    assert await root_cause_autogen.is_generating(tid) is False


@pytest.mark.asyncio
async def test_worker_task_marks_failed_on_other_generate_failure(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> None:
    """Generate() NoCredentialsError DIŞINDA bir istisna fırlatırsa
    sonuç "failed" olmalı — "no_credentials" YALNIZCA o özel duruma
    ayrılmış aksiyona-dönüştürülebilir kod."""
    del fake_redis
    from imga_api.services import root_cause_service
    from imga_api.workers import arq_worker, batch_analyzer

    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_negative_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=60,
        )

    mock_generate = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(root_cause_service.RootCauseService, "generate", mock_generate)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    try:
        await arq_worker.generate_root_causes_task(
            {"worker_context": context}, str(tid), rows_succeeded=60, batch_job_id=str(uuid4())
        )
    finally:
        await context.dispose()

    assert await root_cause_autogen.last_error(tid) == "failed"


@pytest.mark.asyncio
async def test_worker_task_marks_no_error_on_success(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> None:
    """Tüm denenen kategoriler başarılıysa last_error None kalmalı ve
    is_generating False'a düşmeli — mark_started'ın SADD'ı
    mark_finished'ın SREM'iyle tam dengelenir."""
    del fake_redis
    from imga_api.services import root_cause_service
    from imga_api.workers import arq_worker, batch_analyzer

    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_negative_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=60,
        )

    mock_generate = AsyncMock(return_value={"id": str(uuid4())})
    monkeypatch.setattr(root_cause_service.RootCauseService, "generate", mock_generate)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    batch_job_id = uuid4()
    try:
        await arq_worker.generate_root_causes_task(
            {"worker_context": context},
            str(tid),
            rows_succeeded=60,
            batch_job_id=str(batch_job_id),
        )
    finally:
        await context.dispose()

    assert await root_cause_autogen.last_error(tid) is None
    assert await root_cause_autogen.is_generating(tid) is False
