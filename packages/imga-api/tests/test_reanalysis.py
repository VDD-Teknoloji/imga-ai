"""2026-08-10 — siniflandirma kalite elden gecirmesinin DB + API ayagi.

Kapsam:

  * Migration 0041 — ``reviews.experience_type`` kolonu + CHECK +
    kismi indeks; global 9 kategorinin ``description`` backfill'i.
  * Yukleme yolu — birlesik LLM tahminindeki ``experience_type``
    reviews satirina duser (unified yol mock'lanir).
  * Yeniden analiz — yetki (viewer/analyst 403, tenant_admin 201,
    kimliksiz 401), insan duzeltmeli satira DOKUNULMAMASI, yonetici
    ozeti snapshot'larinin dusurulmesi.
  * ``GET /analytics/experience-distribution`` — NULL satirlarin
    eski kategori eslemesine dusmesi, negatif alt sayimi, RLS
    izolasyonu.

pytest bu dosyayi konteyner suitinden kosar; beyaz liste
``infra/imga/test/docker-compose.yml`` icinde.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_core.models import AnalysisResult, CategoryClassification
from imga_db.models import (
    AnalyzeBatchJob,
    ExecutiveSnapshot,
    Review,
    ReviewDecision,
    User,
    UserTenantRole,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.workers import batch_analyzer
from imga_api.workers.batch_analyzer import WorkerContext
from imga_api.workers.reanalyzer import process_reanalysis_job
from tests.batch_helpers import login_token, upload_csv, write_csv

# ---------------------------------------------------------------------
# Yardimcilar
# ---------------------------------------------------------------------


async def _seed_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment_label: str = "NÖTR",
    sentiment_score: float = 0.0,
    primary_category: str = "kargo",
    experience_type: str | None = None,
    overrides_applied: list[dict[str, object]] | None = None,
    review_date: datetime | None = None,
) -> UUID:
    """Tek bir reviews satiri (admin oturumu, RLS baglami set edilir)."""
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        moment = review_date or datetime.now(UTC)
        row = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label=sentiment_label,
            sentiment_score=sentiment_score,
            primary_category=primary_category,
            primary_confidence=0.7,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            batch_job_id=None,
            analyzed_at=moment,
            review_date=moment,
            experience_type=experience_type,
            overrides_applied=overrides_applied,
        )
        admin_session.add(row)
        await admin_session.flush()
        review_id = row.id
        admin_session.expunge(row)
    return review_id


async def _fetch_review(
    admin_session: AsyncSession, review_id: UUID
) -> Review:
    async with admin_session.begin():
        row = await admin_session.get(Review, review_id)
        assert row is not None
        admin_session.expunge(row)
    return row


async def _add_member(
    admin_session: AsyncSession,
    tenant_id: UUID,
    role: UserTenantRole,
) -> tuple[str, str, UUID]:
    """Kuruma verilen rolde ikinci bir kullanici ekler."""
    from imga_api.services import AuditService, UserService

    audit = AuditService(admin_session)
    usvc = UserService(admin_session, audit)
    plain = "Member-Password-123!"
    email = f"role-{uuid4().hex[:8]}@example.com"
    async with admin_session.begin():
        member = await usvc.create(
            email=email, password=plain, full_name=f"Test {role}"
        )
        await usvc.attach_to_tenant(
            user_id=member.id, tenant_id=tenant_id, role=role
        )
        member_id = member.id
    return email, plain, member_id


async def _drop_user(admin_session: AsyncSession, user_id: UUID) -> None:
    async with admin_session.begin():
        await admin_session.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": str(user_id)}
        )


def _fake_unified(
    *,
    sentiment_label: Literal["NEGATIF", "NÖTR", "POZITIF"] = "NEGATIF",
    sentiment_score: float = -0.8,
    category: str = "kargo",
    experience: str | None = "dijital",
    perspective: str | None = None,
) -> Any:
    """``AnalysisPipeline.analyze_batch_unified_async`` yerine gecen
    sahte.

    KRITIK: gercek imza gibi ``perspective_sink`` / ``experience_sink``
    out-param'larini DOLDURUR. Doldurmazsa experience testleri
    "NULL == NULL" ile bos yere gecerdi."""

    async def _impl(
        _self: Any,
        texts: list[str],
        *,
        engine: Any = None,
        available_categories: list[str] | None = None,
        few_shot: tuple[Any, ...] = (),
        stats_sink: dict[str, int] | None = None,
        perspective_options: Any = None,
        perspective_sink: list[str | None] | None = None,
        category_descriptions: dict[str, str] | None = None,
        experience_sink: list[str | None] | None = None,
    ) -> list[AnalysisResult]:
        if perspective_sink is not None:
            perspective_sink.clear()
            perspective_sink.extend([perspective] * len(texts))
        if experience_sink is not None:
            experience_sink.clear()
            experience_sink.extend([experience] * len(texts))
        if stats_sink is not None:
            stats_sink["llm_calls"] = 1
        return [
            AnalysisResult(
                text=t,
                sentiment_label=sentiment_label,
                sentiment_score=sentiment_score,
                overrides_applied=[],
                categorization=CategoryClassification(
                    primary=category, primary_confidence=0.9
                ),
            )
            for t in texts
        ]

    return _impl


async def run_reanalysis_worker(client: TestClient, job_id: UUID) -> None:
    """``tests.batch_helpers.run_worker``'in yeniden analiz ikizi.

    Ayni gerekce: TestClient lifespan'i BlockingPortal'in kendi event
    loop'unda kosar; oradaki WorkerContext'i test loop'undan await
    etmek 'Future attached to a different loop' uretir. Taze context
    her primitifi test loop'una baglar."""
    test_app = client.app  # type: ignore[attr-defined]
    context: WorkerContext = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    try:
        await process_reanalysis_job(job_id, context)
    finally:
        await context.dispose()


def _no_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """RAG embedding cagrisini kes — testte gercek Gemini anahtari yok,
    aksi halde her chunk bir ag zaman asimi bekler."""
    import imga_api.services.embedding_service as embedding_service

    async def _empty(_texts: list[str], _keys: list[Any]) -> list[list[float]]:
        return []

    monkeypatch.setattr(embedding_service, "embed_texts", _empty)


# ---------------------------------------------------------------------
# 1. Migration 0041
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_adds_experience_type_column(
    admin_session: AsyncSession,
) -> None:
    async with admin_session.begin():
        col = (
            await admin_session.execute(
                text(
                    "SELECT data_type, character_maximum_length, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'reviews' "
                    "AND column_name = 'experience_type'"
                )
            )
        ).one_or_none()
    assert col is not None, "reviews.experience_type kolonu yok (0041)"
    assert col.character_maximum_length == 16
    assert col.is_nullable == "YES"


@pytest.mark.asyncio
async def test_migration_adds_check_constraint_and_partial_index(
    admin_session: AsyncSession,
) -> None:
    async with admin_session.begin():
        check = (
            await admin_session.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname = 'ck_reviews_experience_type'"
                )
            )
        ).scalar_one_or_none()
        index = (
            await admin_session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_reviews_tenant_experience_type'"
                )
            )
        ).scalar_one_or_none()
    assert check == "ck_reviews_experience_type"
    assert index is not None
    assert "experience_type IS NOT NULL" in index


@pytest.mark.asyncio
async def test_check_constraint_rejects_unknown_experience_value(
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Kasitli IntegrityError paylasilan admin_session'i zehirleyip
    fixture teardown'ini MissingGreenlet'e dusuruyordu — tek
    kullanimlik oturumla izole edilir."""
    from imga_db import create_engine, create_session_factory

    _user, tid, _pw = semi_auto_tenant
    engine = create_engine("admin")
    try:
        factory = create_session_factory(engine)
        async with factory() as throwaway:
            with pytest.raises(IntegrityError):
                await _seed_review(
                    throwaway,
                    tenant_id=tid,
                    text_value="gecersiz deneyim tipi denemesi",
                    experience_type="hibrit",
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_global_category_descriptions_backfilled(
    admin_session: AsyncSession,
) -> None:
    """0041 backfill'i: 9 global kategorinin tanimi dolu ve kod
    tabanindaki CATEGORY_DESCRIPTIONS_TR ile ayni."""
    from imga_core.categories.taxonomy import CATEGORY_DESCRIPTIONS_TR

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                text(
                    "SELECT code, description FROM categories "
                    "WHERE tenant_id IS NULL AND deleted_at IS NULL"
                )
            )
        ).all()
    by_code = {r.code: r.description for r in rows}
    assert set(CATEGORY_DESCRIPTIONS_TR) <= set(by_code), (
        "global kategori satirlari eksik"
    )
    for code, expected in CATEGORY_DESCRIPTIONS_TR.items():
        assert by_code[code] is not None, f"{code} tanimi backfill edilmemis"
        assert by_code[code] == expected, f"{code} tanimi kod ile ayrismis"


# ---------------------------------------------------------------------
# 2. Yukleme yolunda experience_type kalicilastirma
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_experience_type_persisted_from_unified_prediction(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key-for-unified-path-123")
    _no_embeddings(monkeypatch)

    from imga_core.pipeline import AnalysisPipeline

    monkeypatch.setattr(
        AnalysisPipeline,
        "analyze_batch_unified_async",
        _fake_unified(experience="operasyonel", category="iade"),
    )

    token = login_token(batch_client, user.email, pw, tid)
    path = write_csv(
        tmp_path / "exp.csv",
        ["yorum"],
        [["Iade surecini bir turlu baslatamadim"], ["Paket eksik geldi"]],
    )
    r = upload_csv(batch_client, token=token, path=path, text_column="yorum")
    assert r.status_code == 201, r.text
    job_id = UUID(r.json()["job_id"])

    from tests.batch_helpers import run_worker

    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        rows = (
            await admin_session.execute(
                select(Review.experience_type, Review.primary_category)
                .where(Review.tenant_id == tid)
            )
        ).all()
    assert len(rows) == 2
    assert {row.experience_type for row in rows} == {"operasyonel"}
    assert {row.primary_category for row in rows} == {"iade"}


@pytest.mark.asyncio
async def test_invalid_experience_value_lands_as_null(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Model sozlesme disi bir deger dondururse CHECK ihlali ile TUM
    chunk transaction'i patlamamali — satir NULL'a duser."""
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key-for-unified-path-123")
    _no_embeddings(monkeypatch)

    from imga_core.pipeline import AnalysisPipeline

    monkeypatch.setattr(
        AnalysisPipeline,
        "analyze_batch_unified_async",
        _fake_unified(experience="DIJITAL-ISH"),
    )

    token = login_token(batch_client, user.email, pw, tid)
    path = write_csv(tmp_path / "bad.csv", ["yorum"], [["Kargo gec geldi"]])
    r = upload_csv(batch_client, token=token, path=path, text_column="yorum")
    assert r.status_code == 201, r.text

    from tests.batch_helpers import run_worker

    await run_worker(batch_client, UUID(r.json()["job_id"]))

    async with admin_session.begin():
        values = (
            (
                await admin_session.execute(
                    select(Review.experience_type).where(Review.tenant_id == tid)
                )
            )
            .scalars()
            .all()
        )
    assert values == [None]


def test_normalize_experience_type_contract() -> None:
    from imga_api.workers.batch_analyzer import normalize_experience_type

    assert normalize_experience_type("dijital") == "dijital"
    assert normalize_experience_type("  Operasyonel  ") == "operasyonel"
    assert normalize_experience_type("hibrit") is None
    assert normalize_experience_type(None) is None


# ---------------------------------------------------------------------
# 3. Yeniden analiz — yetki
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reanalyze_all_requires_authentication(
    batch_client: TestClient,
) -> None:
    r = batch_client.post("/tenants/me/reviews/reanalyze-all")
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(
    "role", [UserTenantRole.VIEWER, UserTenantRole.ANALYST]
)
@pytest.mark.asyncio
async def test_reanalyze_all_forbidden_for_non_admin(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    role: UserTenantRole,
) -> None:
    _user, tid, _pw = semi_auto_tenant
    email, plain, member_id = await _add_member(admin_session, tid, role)
    try:
        token = login_token(batch_client, email, plain, tid)
        r = batch_client.post(
            "/tenants/me/reviews/reanalyze-all",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text
    finally:
        await _drop_user(admin_session, member_id)


@pytest.mark.asyncio
async def test_reanalyze_all_creates_job_for_tenant_admin(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed_review(
        admin_session, tenant_id=tid, text_value="Kargom hala gelmedi"
    )
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reviews/reanalyze-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["total_rows"] == 1
    assert body["file_name"].startswith("yeniden-analiz:")


@pytest.mark.asyncio
async def test_reanalyze_all_400_when_no_candidates(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Aday yoksa aninda COMPLETED'a dusecek sahte is acilmaz."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reviews/reanalyze-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_batch_scoped_reanalyze_authz_and_scope(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    tmp_path: Any,
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    path = write_csv(
        tmp_path / "scope.csv", ["yorum"], [["Kargo cok gec geldi"]]
    )
    up = upload_csv(batch_client, token=token, path=path, text_column="yorum")
    assert up.status_code == 201, up.text
    source_job_id = UUID(up.json()["job_id"])

    from tests.batch_helpers import run_worker

    await run_worker(batch_client, source_job_id)

    # analyst reddedilir
    email, plain, member_id = await _add_member(
        admin_session, tid, UserTenantRole.ANALYST
    )
    try:
        analyst_token = login_token(batch_client, email, plain, tid)
        forbidden = batch_client.post(
            f"/tenants/me/analyze/batch/{source_job_id}/reanalyze",
            headers={"Authorization": f"Bearer {analyst_token}"},
        )
        assert forbidden.status_code == 403, forbidden.text
    finally:
        await _drop_user(admin_session, member_id)

    ok = batch_client.post(
        f"/tenants/me/analyze/batch/{source_job_id}/reanalyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 201, ok.text
    new_job_id = UUID(ok.json()["job_id"])
    assert new_job_id != source_job_id
    assert ok.json()["total_rows"] == 1

    # Yeniden analizin yeniden analizi 409
    again = batch_client.post(
        f"/tenants/me/analyze/batch/{new_job_id}/reanalyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert again.status_code == 409, again.text

    missing = batch_client.post(
        f"/tenants/me/analyze/batch/{uuid4()}/reanalyze",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404, missing.text


# ---------------------------------------------------------------------
# 4. Yeniden analiz mekanigi
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reanalysis_updates_rows_but_skips_human_corrections(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key-for-unified-path-123")
    _no_embeddings(monkeypatch)

    fresh_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Uygulamada kargo statusu yanlis gorunuyor",
        sentiment_label="NÖTR",
        sentiment_score=0.0,
        primary_category="belirsiz",
    )
    corrected_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Insan bu yorumu elle duzeltti, dokunulmasin",
        sentiment_label="POZITIF",
        sentiment_score=0.9,
        primary_category="musteri_hizmetleri",
        overrides_applied=[{"layer": "user_correction", "detail": "elle"}],
    )

    from imga_core.pipeline import AnalysisPipeline

    monkeypatch.setattr(
        AnalysisPipeline,
        "analyze_batch_unified_async",
        _fake_unified(
            sentiment_label="NEGATIF",
            sentiment_score=-0.8,
            category="kargo",
            experience="dijital",
        ),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reviews/reanalyze-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    # Aday sayimi insan duzeltmeli satiri DISLAR.
    assert r.json()["total_rows"] == 1
    job_id = UUID(r.json()["job_id"])

    await run_reanalysis_worker(batch_client, job_id)

    fresh = await _fetch_review(admin_session, fresh_id)
    assert fresh.sentiment_label == "NEGATIF"
    assert fresh.primary_category == "kargo"
    assert fresh.experience_type == "dijital"
    layers = [o.get("layer") for o in (fresh.overrides_applied or [])]
    assert "reanalysis" in layers

    corrected = await _fetch_review(admin_session, corrected_id)
    assert corrected.sentiment_label == "POZITIF"
    assert corrected.sentiment_score == 0.9
    assert corrected.primary_category == "musteri_hizmetleri"
    assert corrected.experience_type is None
    corrected_layers = [
        o.get("layer") for o in (corrected.overrides_applied or [])
    ]
    assert "reanalysis" not in corrected_layers

    async with admin_session.begin():
        job = await admin_session.get(AnalyzeBatchJob, job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.processed_rows == 1
        assert job.succeeded_rows == 1
        assert job.last_checkpoint_row == 1


@pytest.mark.asyncio
async def test_reanalysis_preserves_review_date_and_nps(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yeniden analiz SINIFLANDIRMAYI tazeler; tarih/NPS/karar kalir."""
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key-for-unified-path-123")
    _no_embeddings(monkeypatch)

    original_date = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Eski arsiv yorumu, tarihi korunmali",
        review_date=original_date,
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        await admin_session.execute(
            text("UPDATE reviews SET nps_score = 3 WHERE id = :i"),
            {"i": str(review_id)},
        )

    from imga_core.pipeline import AnalysisPipeline

    monkeypatch.setattr(
        AnalysisPipeline, "analyze_batch_unified_async", _fake_unified()
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reviews/reanalyze-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    await run_reanalysis_worker(batch_client, UUID(r.json()["job_id"]))

    row = await _fetch_review(admin_session, review_id)
    assert row.review_date == original_date
    assert row.nps_score == 3
    assert row.decision == ReviewDecision.SKIPPED_THRESHOLD
    assert row.sentiment_label == "NEGATIF"


@pytest.mark.asyncio
async def test_reanalysis_busts_executive_snapshots(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yeniden analiz GECMISI degistirir — bugunun degil TUM
    tarihlerin snapshot'lari dusmeli."""
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(tid, "fake-key-for-unified-path-123")
    _no_embeddings(monkeypatch)

    await _seed_review(
        admin_session, tenant_id=tid, text_value="Snapshot bust denemesi"
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ExecutiveSnapshot(
                tenant_id=tid,
                snapshot_date=datetime(2026, 1, 5, tzinfo=UTC).date(),
                period="daily",
                metrics={"stale": True},
                review_count_at_snapshot=1,
            )
        )

    from imga_core.pipeline import AnalysisPipeline

    monkeypatch.setattr(
        AnalysisPipeline, "analyze_batch_unified_async", _fake_unified()
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reviews/reanalyze-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    await run_reanalysis_worker(batch_client, UUID(r.json()["job_id"]))

    async with admin_session.begin():
        remaining = (
            (
                await admin_session.execute(
                    select(ExecutiveSnapshot.id).where(
                        ExecutiveSnapshot.tenant_id == tid
                    )
                )
            )
            .scalars()
            .all()
        )
    assert remaining == []


@pytest.mark.asyncio
async def test_reanalysis_fails_cleanly_without_llm_credentials(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BERT yedegi ACIK olsa bile yeniden analiz ona DUSMEZ."""
    user, tid, pw = semi_auto_tenant
    monkeypatch.setenv("IMGA_BATCH_BERT_FALLBACK", "true")
    await _seed_review(
        admin_session, tenant_id=tid, text_value="Anahtarsiz kurum yorumu"
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/reviews/reanalyze-all",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    job_id = UUID(r.json()["job_id"])
    await run_reanalysis_worker(batch_client, job_id)

    detail = batch_client.get(
        f"/tenants/me/analyze/batch/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "failed"
    assert body["last_error"] is not None
    assert "BERT" in body["last_error"]


@pytest.mark.asyncio
async def test_candidate_predicate_keeps_null_overrides_rows(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """``overrides_applied`` NULL olan eski satirlar aday KALMALI —
    ``NOT (col @> ...)`` NULL uretip onlari sessizce elerdi."""
    from imga_api.workers.reanalyzer import candidate_stmt, count_candidates

    _user, tid, _pw = semi_auto_tenant
    legacy_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="0014 oncesi arsiv satiri, overrides NULL",
        overrides_applied=None,
    )
    empty_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Override calismis ama hicbiri tetiklenmemis",
        overrides_applied=[],
    )
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Anlamsal duzeltme damgali satir",
        overrides_applied=[{"layer": "user_correction_semantic"}],
    )
    await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="KB duzeltmesi damgali satir",
        overrides_applied=[{"layer": "user_correction_kb"}],
    )

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        ids = (
            (
                await admin_session.execute(
                    candidate_stmt(tenant_id=tid, source_batch_job_id=None)
                )
            )
            .scalars()
            .all()
        )
        total = await count_candidates(
            admin_session, tenant_id=tid, source_batch_job_id=None
        )
    assert set(ids) == {legacy_id, empty_id}
    # Route'un sayimi ile iscinin listesi AYNI yuklemi kullanmali.
    assert total == len(ids) == 2


# ---------------------------------------------------------------------
# 5. /analytics/experience-distribution
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_experience_distribution_math_and_null_fallback(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant

    # Kolonu DOLU satirlar — model karari her zaman kazanir. Kategorisi
    # 'kargo' olmasina ragmen dijital sayilmali.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="model dijital der 1",
        primary_category="kargo", experience_type="dijital",
        sentiment_label="NEGATIF", sentiment_score=-0.9,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="model dijital der 2",
        primary_category="kargo", experience_type="dijital",
        sentiment_label="POZITIF", sentiment_score=0.9,
    )
    # Kolonu DOLU + operasyonel, kategorisi teknik_destek (yedek yol
    # dijital derdi) — model karari yine kazanmali.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="model operasyonel der",
        primary_category="teknik_destek", experience_type="operasyonel",
        sentiment_label="NEGATIF", sentiment_score=-0.7,
    )
    # NULL satirlar — kategori eslemesine duser.
    await _seed_review(
        admin_session, tenant_id=tid, text_value="eski satir teknik",
        primary_category="teknik_destek", experience_type=None,
        sentiment_label="NEGATIF", sentiment_score=-0.5,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="eski satir fatura",
        primary_category="faturalama", experience_type=None,
        sentiment_label="NÖTR", sentiment_score=0.0,
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="eski satir iade",
        primary_category="iade", experience_type=None,
        sentiment_label="POZITIF", sentiment_score=0.6,
    )
    # belirsiz hicbir kovaya girmez -> atanmamis
    await _seed_review(
        admin_session, tenant_id=tid, text_value="eski satir belirsiz",
        primary_category="belirsiz", experience_type=None,
        sentiment_label="NEGATIF", sentiment_score=-0.4,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/experience-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # dijital: 2 model karari + 2 NULL yedek (teknik_destek, faturalama)
    assert body["dijital"]["total"] == 4
    assert body["dijital"]["negatif"] == 2
    # operasyonel: 1 model karari + 1 NULL yedek (iade)
    assert body["operasyonel"]["total"] == 2
    assert body["operasyonel"]["negatif"] == 1
    # atanmamis: yalniz 'belirsiz'
    assert body["atanmamis"]["total"] == 1
    assert body["atanmamis"]["negatif"] == 1


@pytest.mark.asyncio
async def test_experience_distribution_accepts_iso_datetime_window(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Frontend ISO datetime yollar — ``date`` tipi 422 uretirdi."""
    user, tid, pw = semi_auto_tenant
    await _seed_review(
        admin_session, tenant_id=tid, text_value="ocak yorumu",
        primary_category="teknik_destek",
        review_date=datetime(2026, 1, 10, 9, 30, tzinfo=UTC),
    )
    await _seed_review(
        admin_session, tenant_id=tid, text_value="mart yorumu",
        primary_category="iade",
        review_date=datetime(2026, 3, 10, 9, 30, tzinfo=UTC),
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/analytics/experience-distribution",
        params={
            "date_from": "2026-03-01T00:00:00Z",
            "date_to": "2026-03-31T23:59:59Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["operasyonel"]["total"] == 1
    assert body["dijital"]["total"] == 0


@pytest.mark.asyncio
async def test_experience_distribution_accepts_batch_job_id(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    tmp_path: Any,
) -> None:
    """Frontend daha sonra baglayacak; parametre simdiden calismali."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    path = write_csv(tmp_path / "b.csv", ["yorum"], [["Kargo gec geldi"]])
    up = upload_csv(batch_client, token=token, path=path, text_column="yorum")
    assert up.status_code == 201, up.text
    job_id = UUID(up.json()["job_id"])

    from tests.batch_helpers import run_worker

    await run_worker(batch_client, job_id)

    # Batch disinda ekstra bir satir
    await _seed_review(
        admin_session, tenant_id=tid, text_value="manuel satir",
        primary_category="teknik_destek",
    )

    scoped = batch_client.get(
        "/tenants/me/analytics/experience-distribution",
        params={"batch_job_id": str(job_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert scoped.status_code == 200, scoped.text
    scoped_total = sum(
        scoped.json()[k]["total"]
        for k in ("dijital", "operasyonel", "atanmamis")
    )
    assert scoped_total == 1

    unscoped = batch_client.get(
        "/tenants/me/analytics/experience-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    unscoped_total = sum(
        unscoped.json()[k]["total"]
        for k in ("dijital", "operasyonel", "atanmamis")
    )
    assert unscoped_total == 2


@pytest.mark.asyncio
async def test_experience_distribution_is_rls_isolated(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    manual_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user_a, tid_a, pw_a = semi_auto_tenant
    _user_b, tid_b, _pw_b = manual_tenant

    await _seed_review(
        admin_session, tenant_id=tid_a, text_value="A kurumunun yorumu",
        primary_category="teknik_destek",
    )
    for i in range(3):
        await _seed_review(
            admin_session, tenant_id=tid_b, text_value=f"B kurumu yorumu {i}",
            primary_category="teknik_destek",
        )

    token = login_token(batch_client, user_a.email, pw_a, tid_a)
    r = batch_client.get(
        "/tenants/me/analytics/experience-distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dijital"]["total"] == 1
    total = sum(
        body[k]["total"] for k in ("dijital", "operasyonel", "atanmamis")
    )
    assert total == 1, "baska kurumun satirlari sizdi"


@pytest.mark.asyncio
async def test_experience_distribution_open_to_viewer(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    _user, tid, _pw = semi_auto_tenant
    email, plain, member_id = await _add_member(
        admin_session, tid, UserTenantRole.VIEWER
    )
    try:
        token = login_token(batch_client, email, plain, tid)
        r = batch_client.get(
            "/tenants/me/analytics/experience-distribution",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
    finally:
        await _drop_user(admin_session, member_id)


# ---------------------------------------------------------------------
# 6. Review wire shape
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_list_and_detail_expose_experience_type(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    filled_id = await _seed_review(
        admin_session, tenant_id=tid, text_value="deneyim tipi dolu satir",
        experience_type="dijital",
    )
    legacy_id = await _seed_review(
        admin_session, tenant_id=tid, text_value="deneyim tipi bos satir",
    )

    token = login_token(batch_client, user.email, pw, tid)
    listing = batch_client.get(
        "/tenants/me/reviews",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200, listing.text
    by_id = {item["id"]: item for item in listing.json()["items"]}
    assert by_id[str(filled_id)]["experience_type"] == "dijital"
    assert by_id[str(legacy_id)]["experience_type"] is None

    detail = batch_client.get(
        f"/tenants/me/reviews/{filled_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["experience_type"] == "dijital"
