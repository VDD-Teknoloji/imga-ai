"""2026-08-18 (migration 0042) "büyük paket" WS2 — batch worker veri
kalitesi write-path coverage.

Requires live Postgres (RLS is a Postgres-only feature); part of the
server test-compose suite, not runnable standalone without :5433.

Covers:
  * boş metin artık bir Review satırı olarak yazılır (quality_flag=
    'empty', decision=SKIPPED_QUALITY) — test_batch_upload.py'deki
    eski "empty->failed" testi de bu davranışa göre güncellendi.
  * KRİTİK: ikinci boş satır 'duplicate' damgalanmaz (hash("") tuzağı).
  * intra-batch + cross-batch tekrarın quality_flag='duplicate' alması,
    cross-batch'in içerik-kalitesi heuristiğinin ÖNÜNE geçmesi.
  * entered_by (5. business dimension) + source (şablonun 'kaynak'
    kolonu) kalıcılığı — opt-out ve auto_create (record_and_decide
    back-fill) yazım yollarının ikisinde de.
  * classify_data_quality'nin motor yolundan (unified/classic)
    bağımsız çalışması — burada LLM anahtarı yok, klasik/keyword yolu
    koşuyor ve heuristik yine de quality_flag'i dolduruyor.
  * WS1 dinamik kategori kümesi (_load_tenant_category_snapshot):
    devre dışı global kümeden düşer, etkin custom kümeye girer,
    'belirsiz' her zaman garanti, hiç etkin kategori kalmazsa tüm
    globallere güvenli geri dönüş.
  * 2026-08-21 (migration 0046) — operasyonel facts (SLA/CSAT/efor/
    tazmin/teslimat): tenant_fact_mappings ile eşlenen kolonlar
    review_facts'e parse edilerek yazılır — opt-out ve auto_create
    yollarının ikisinde de, ve boş-metinli satırlarda da (facts metin
    hücresinden bağımsız).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from cachetools import TTLCache
from fastapi.testclient import TestClient
from imga_core.categories.taxonomy import GLOBAL_CATEGORY_CODES
from imga_db.models import (
    BatchJobStatus,
    Category,
    Review,
    ReviewDecision,
    ReviewFact,
    TenantBusinessDimension,
    TenantFactMapping,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.audit_service import AuditService
from imga_api.services.tenant_config_service import TenantConfigService
from imga_api.workers.batch_analyzer import _load_tenant_category_snapshot
from tests.batch_helpers import fetch_job, login_token, run_worker, upload_csv, write_csv

_SET_TENANT_SQL = text("SELECT set_config('app.current_tenant_id', :t, true)")


async def _bind(admin_session: AsyncSession, tenant_id: UUID) -> None:
    await admin_session.execute(_SET_TENANT_SQL, {"t": str(tenant_id)})


# ---------------------------------------------------------------------------
# Empty text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_rows_persist_with_quality_flag_not_failed(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Davranış değişikliği (bkz. test_batch_upload.py'deki yeniden
    adlandırılmış test için de aynı gerekçe): boş satırlar artık
    'failed' değil, quality_flag='empty' + decision=SKIPPED_QUALITY
    ile bir Review satırı olarak yazılır; NÖTR/0.0/'belirsiz'/0.0
    sabit değerleriyle."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "mixed.csv",
        ["yorum"],
        [
            ["dolu satır metni burada"],
            [""],
            ["başka dolu satır metni"],
            ["   "],
        ],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)

    assert job.processed_rows == 4
    assert job.succeeded_rows == 4  # empty rows count as succeeded now
    assert job.failed_rows == 0
    assert job.quality_empty_rows == 2

    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            (
                await admin_session.execute(
                    select(Review).where(Review.batch_job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
    empty_rows = [row for row in rows if row.quality_flag == "empty"]
    assert len(empty_rows) == 2
    for row in empty_rows:
        assert row.decision == ReviewDecision.SKIPPED_QUALITY
        assert row.decision_reason == "empty_text"
        assert row.sentiment_label == "NÖTR"
        assert row.sentiment_score == 0.0
        assert row.primary_category == "belirsiz"
        assert row.primary_confidence == 0.0
        assert row.text == ""


@pytest.mark.asyncio
async def test_second_empty_row_is_not_marked_duplicate(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """KRİTİK: boş metnin hash'i seen_hashes'e HİÇ girmez — girseydi
    hash("") her zaman aynı değeri üretir ve ikinci boş satır intra-
    batch dedup'a takılıp quality_flag='duplicate' damgalanırdı. Bu
    test tüm chunk'ı boş metinden oluşturarak valid_rows'un TAMAMEN
    boş olduğu (BERT/LLM'e hiç girilmeyen) kod yolunu da kapsar."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "all_empty.csv",
        ["yorum"],
        [[""], [""], ["   "]],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)

    assert job.status == BatchJobStatus.COMPLETED
    assert job.succeeded_rows == 3
    assert job.failed_rows == 0
    assert job.quality_empty_rows == 3
    assert job.quality_duplicate_rows == 0
    assert job.duplicates_skipped == 0

    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            (
                await admin_session.execute(
                    select(Review).where(Review.batch_job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3
    assert all(row.quality_flag == "empty" for row in rows)
    assert all(row.decision == ReviewDecision.SKIPPED_QUALITY for row in rows)


# ---------------------------------------------------------------------------
# Duplicate flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intra_batch_duplicate_gets_quality_flag(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "dup.csv",
        ["yorum"],
        [
            ["tekrarlanan bir metin burada"],
            ["farklı bir metin buraya"],
            ["tekrarlanan bir metin burada"],
        ],
    )
    r = upload_csv(batch_client, token=token, path=csv_path, text_column="yorum")
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)

    assert job.quality_duplicate_rows == 1
    assert job.duplicates_skipped == 1

    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            (
                await admin_session.execute(
                    select(Review).where(Review.batch_job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
    flagged = [row for row in rows if row.quality_flag == "duplicate"]
    assert len(flagged) == 1
    assert flagged[0].decision == ReviewDecision.SKIPPED_DEDUP


@pytest.mark.asyncio
async def test_cross_batch_dedup_quality_flag_beats_content_heuristic(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """record_and_decide'ın kendi SKIPPED_DEDUP kararı 'duplicate'
    olarak damgalanır — metin İÇERİK olarak informational/meaningless
    heuristiğine uysa bile (bu metin uymuyor zaten, ama öncelik
    kuralını test etmek için) dedup her zaman kazanır (0042 backfill
    semantiğiyle tutarlı)."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    # 4+ kargo keyword hit'i semi_auto eşiğini (confidence > 0.7) geçsin
    # diye — test_batch_dedup.py'deki aynı kalıp.
    repeat_text = (
        "kargom kargocu gelmedi, teslimat ulaşmadı, "
        "takip kodu yanlış, çok kötü hizmet"
    )

    csv1 = write_csv(tmp_path / "first.csv", ["yorum"], [[repeat_text]])
    r1 = upload_csv(
        batch_client, token=token, path=csv1, text_column="yorum",
        auto_create_tickets=True,
    )
    job1 = UUID(r1.json()["job_id"])
    await run_worker(batch_client, job1)
    job_obj1 = await fetch_job(admin_session, job1)
    assert job_obj1.tickets_created == 1

    csv2 = write_csv(tmp_path / "second.csv", ["yorum"], [[repeat_text]])
    r2 = upload_csv(
        batch_client, token=token, path=csv2, text_column="yorum",
        auto_create_tickets=True,
    )
    job2 = UUID(r2.json()["job_id"])
    await run_worker(batch_client, job2)
    job_obj2 = await fetch_job(admin_session, job2)

    assert job_obj2.tickets_created == 0
    assert job_obj2.quality_duplicate_rows == 1
    assert job_obj2.quality_informational_rows == 0
    assert job_obj2.quality_meaningless_rows == 0

    async with admin_session.begin():
        await _bind(admin_session, tid)
        review = (
            await admin_session.execute(
                select(Review)
                .where(Review.batch_job_id == job2)
                .where(Review.decision == ReviewDecision.SKIPPED_DEDUP)
            )
        ).scalar_one()
    assert review.quality_flag == "duplicate"


# ---------------------------------------------------------------------------
# entered_by + source persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entered_by_and_source_persist_opt_out_path(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """entered_by (5. business dimension) + source (şablonun 'kaynak'
    kolonu) kalıcı — opt-out (auto_create_tickets=False) direkt-insert
    dalı. 'kaynak' bugüne kadar parse edilip düşürülüyordu (mevcut
    kırık); artık reviews.source'a yazılıyor."""
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

    csv_path = write_csv(
        tmp_path / "attrib.csv",
        ["yorum", "calisan", "kaynak"],
        [["ürünle ilgili genel bir yorum metni burada", "Ahmet Yılmaz", "web"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        source_column="kaynak",
        auto_create_tickets=False,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        row = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalar_one()
    assert row.entered_by == "Ahmet Yılmaz"
    assert row.source == "web"
    assert row.decision == ReviewDecision.SKIPPED_MODE


@pytest.mark.asyncio
async def test_entered_by_and_source_persist_auto_create_backfill_path(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Aynı iki alan, record_and_decide back-fill UPDATE deseni
    üzerinden — auto_create_tickets=True (bridge çağrılır, imza
    genişletilmedi)."""
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

    csv_path = write_csv(
        tmp_path / "attrib_auto.csv",
        ["yorum", "calisan", "kaynak"],
        [["ürünle ilgili başka genel bir yorum metni", "Ayşe Demir", "mobil"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        source_column="kaynak",
        auto_create_tickets=True,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        row = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalar_one()
    assert row.entered_by == "Ayşe Demir"
    assert row.source == "mobil"


# ---------------------------------------------------------------------------
# operational facts (migration 0046) — SLA/CSAT/efor/tazmin/teslimat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facts_persist_via_opt_out_path(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """tenant_fact_mappings ile eşlenen SLA statü + süre kolonları,
    yükleme sonrası review_facts satırına PARSE EDİLMİŞ olarak yazılır
    (opt-out / direkt-insert dalı — auto_create_tickets=False)."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    async with admin_session.begin():
        admin_session.add(
            TenantFactMapping(
                tenant_id=tid,
                fact_field="sla_resolution_status",
                csv_column_mapping="cozum_durumu",
                enabled=True,
            )
        )
        admin_session.add(
            TenantFactMapping(
                tenant_id=tid,
                fact_field="resolution_time",
                csv_column_mapping="cozum_suresi",
                enabled=True,
            )
        )

    csv_path = write_csv(
        tmp_path / "facts_opt_out.csv",
        ["yorum", "cozum_durumu", "cozum_suresi"],
        [["ürünle ilgili genel bir yorum metni burada", "Within SLA", "00:14:19"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=False,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        review_row = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalar_one()
        fact_row = (
            await admin_session.execute(
                select(ReviewFact).where(ReviewFact.review_id == review_row.id)
            )
        ).scalar_one()
    assert fact_row.sla_resolution_status == "within"
    assert fact_row.resolution_time_minutes == 14


@pytest.mark.asyncio
async def test_facts_persist_via_auto_create_path(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Aynı senaryo, record_and_decide (auto_create_tickets=True) yolu
    üzerinden — result.review_id doğrudan bilindiği için facts o id'ye
    yazılır."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    async with admin_session.begin():
        admin_session.add(
            TenantFactMapping(
                tenant_id=tid,
                fact_field="csat",
                csv_column_mapping="anket",
                enabled=True,
            )
        )

    csv_path = write_csv(
        tmp_path / "facts_auto_create.csv",
        ["yorum", "anket"],
        [["ürünle ilgili başka bir yorum metni burada", "Çok memnunum"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=True,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        review_row = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalar_one()
        fact_row = (
            await admin_session.execute(
                select(ReviewFact).where(ReviewFact.review_id == review_row.id)
            )
        ).scalar_one()
    assert fact_row.csat_score == 5
    assert fact_row.csat_raw == "Çok memnunum"


@pytest.mark.asyncio
async def test_facts_persist_for_empty_text_row(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Boş-metinli satır quality_flag='empty' olarak yazılır AMA facts
    kolonu doluysa review_facts YİNE DE yazılır — facts metin
    hücresinden bağımsızdır (spec: 'Boş-metin ... dahil — facts her
    persist edilen review için yazılır')."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    async with admin_session.begin():
        admin_session.add(
            TenantFactMapping(
                tenant_id=tid,
                fact_field="csat",
                csv_column_mapping="anket",
                enabled=True,
            )
        )

    csv_path = write_csv(
        tmp_path / "facts_empty_text.csv",
        ["yorum", "anket"],
        [
            ["dolu bir yorum metni burada, facts kolonu boş", ""],
            ["", "Orta"],
        ],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=False,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        empty_review = (
            await admin_session.execute(
                select(Review)
                .where(Review.batch_job_id == job_id)
                .where(Review.quality_flag == "empty")
            )
        ).scalar_one()
        fact_row = (
            await admin_session.execute(
                select(ReviewFact).where(ReviewFact.review_id == empty_review.id)
            )
        ).scalar_one()
    assert fact_row.csat_score == 3
    assert fact_row.csat_raw == "Orta"


@pytest.mark.asyncio
async def test_no_fact_mapping_means_no_review_facts_row(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """Kurumun hiç tenant_fact_mappings satırı yoksa, upload'ta facts
    kolonu OLSA BİLE eşlenmediği için review_facts hiç yazılmaz."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    csv_path = write_csv(
        tmp_path / "facts_no_mapping.csv",
        ["yorum", "anket"],
        [["mükemmel bir hizmet aldım gerçekten çok memnun kaldım", "Çok memnunum"]],
    )
    r = upload_csv(
        batch_client,
        token=token,
        path=csv_path,
        text_column="yorum",
        auto_create_tickets=False,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        review_row = (
            await admin_session.execute(
                select(Review).where(Review.batch_job_id == job_id)
            )
        ).scalar_one()
        fact_row = (
            await admin_session.execute(
                select(ReviewFact).where(ReviewFact.review_id == review_row.id)
            )
        ).scalar_one_or_none()
    assert fact_row is None


# ---------------------------------------------------------------------------
# informational / meaningless — engine-independent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_informational_and_meaningless_flags_set_via_auto_create_path(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
    tmp_path: Path,
    admin_session: AsyncSession,
) -> None:
    """classify_data_quality motor yolundan (unified/classic) bağımsız
    çalışır — bu test ortamında tenant'ın LLM anahtarı yok, yani klasik
    (BERT-stub + keyword) yol koşuyor; heuristik yine de quality_flag'i
    dolduruyor. decision akışı DEĞİŞMEZ: manual tenant hiçbir satırda
    ticket açmaz (tickets_created kalıyor 0)."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    informational_text = "Değerli müşterimiz, siparişiniz kargoya verildi."
    meaningless_text = "Tamam"
    normal_text = (
        "Kargom bugün gelmedi, çok mağdur oldum, yardım rica ediyorum."
    )

    csv_path = write_csv(
        tmp_path / "quality.csv",
        ["yorum"],
        [[informational_text], [meaningless_text], [normal_text]],
    )
    r = upload_csv(
        batch_client, token=token, path=csv_path, text_column="yorum",
        auto_create_tickets=True,
    )
    job_id = UUID(r.json()["job_id"])
    await run_worker(batch_client, job_id)
    job = await fetch_job(admin_session, job_id)

    assert job.quality_informational_rows == 1
    assert job.quality_meaningless_rows == 1
    assert job.tickets_created == 0  # manual mode never mints tickets

    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            await admin_session.execute(
                select(Review.text, Review.quality_flag).where(
                    Review.batch_job_id == job_id
                )
            )
        ).all()
    by_text = {row.text: row.quality_flag for row in rows}
    assert by_text[informational_text] == "informational"
    assert by_text[meaningless_text] == "meaningless"
    assert by_text[normal_text] is None


# ---------------------------------------------------------------------------
# WS1 — dynamic category snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_category_snapshot_excludes_disabled_global_includes_custom(
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    """Dinamik kod kümesi: devre dışı bırakılan global kod kümede
    OLMAMALI, etkin custom kategori kümede OLMALI, 'belirsiz' her
    durumda garanti, descriptions kod kümesiyle tutarlı."""
    user, tid, _pw = manual_tenant

    async with admin_session.begin():
        await _bind(admin_session, tid)
        pazarlama_id = (
            await admin_session.execute(
                select(Category.id).where(
                    Category.tenant_id.is_(None), Category.code == "pazarlama"
                )
            )
        ).scalar_one()
        audit = AuditService(admin_session)
        config_service = TenantConfigService(
            admin_session, audit, TTLCache(maxsize=100, ttl=300)
        )
        await config_service.toggle_category(
            tid, pazarlama_id, is_enabled=False, actor_user_id=user.id
        )
        await config_service.create_custom_category(
            tid,
            code="ozel_kategori",
            label_tr="Özel Kategori",
            actor_user_id=user.id,
        )

    async with admin_session.begin():
        snapshot = await _load_tenant_category_snapshot(admin_session, tid)

    assert "pazarlama" not in snapshot.codes
    assert "ozel_kategori" in snapshot.codes
    assert "belirsiz" in snapshot.codes
    assert "kargo" in snapshot.codes  # still-enabled global stays
    assert set(snapshot.descriptions.keys()).issubset(set(snapshot.codes))


@pytest.mark.asyncio
async def test_category_snapshot_falls_back_to_all_globals_when_none_enabled(
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    """Güvenli geri dönüş: tenant'ın hiç etkin kategorisi (global+
    custom toplamı) kalmamışsa TÜM globallere düşülür — aksi halde
    prompt'a giden kod kümesi boşalır ve her satır zorunlu 'belirsiz'
    sınıflandırılırdı."""
    user, tid, _pw = manual_tenant

    async with admin_session.begin():
        await _bind(admin_session, tid)
        global_ids = (
            (
                await admin_session.execute(
                    select(Category.id).where(Category.tenant_id.is_(None))
                )
            )
            .scalars()
            .all()
        )
        audit = AuditService(admin_session)
        config_service = TenantConfigService(
            admin_session, audit, TTLCache(maxsize=100, ttl=300)
        )
        for cat_id in global_ids:
            await config_service.toggle_category(
                tid, cat_id, is_enabled=False, actor_user_id=user.id
            )

    async with admin_session.begin():
        snapshot = await _load_tenant_category_snapshot(admin_session, tid)

    assert set(GLOBAL_CATEGORY_CODES).issubset(set(snapshot.codes))
    assert "belirsiz" in snapshot.codes


@pytest.mark.asyncio
async def test_category_snapshot_custom_only_does_not_trigger_fallback(
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    """Tenant bilinçli olarak TÜM globalleri kapatıp yalnız custom
    taksonomiye güveniyorsa (A-sistemi senaryosu), güvenli geri dönüş
    TETİKLENMEMELİ — combined küme custom kod sayesinde boş değildir."""
    user, tid, _pw = manual_tenant

    async with admin_session.begin():
        await _bind(admin_session, tid)
        global_ids = (
            (
                await admin_session.execute(
                    select(Category.id).where(Category.tenant_id.is_(None))
                )
            )
            .scalars()
            .all()
        )
        audit = AuditService(admin_session)
        config_service = TenantConfigService(
            admin_session, audit, TTLCache(maxsize=100, ttl=300)
        )
        for cat_id in global_ids:
            await config_service.toggle_category(
                tid, cat_id, is_enabled=False, actor_user_id=user.id
            )
        await config_service.create_custom_category(
            tid,
            code="tek_kategori",
            label_tr="Tek Kategori",
            actor_user_id=user.id,
        )

    async with admin_session.begin():
        snapshot = await _load_tenant_category_snapshot(admin_session, tid)

    assert snapshot.codes == ["tek_kategori", "belirsiz"]
