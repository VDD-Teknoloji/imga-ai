"""Sprint 11.0 — düzeltme-geri-besleme regression testleri.

Kapsam:
  * POST /tenants/me/reviews/{id}/correct — karar güncellenir,
    override trace'e user_correction düşer, correction satırı oluşur.
  * Doğrulamalar: değişiklik yok → 400; bilinmeyen kategori → 400;
    viewer → 403.
  * pgvector yolu: embedding'li correction insert + cosine komşu
    sorgusu (asyncpg + vector tipi gerçek DB'de doğrulanır).
  * Worker birebir-düzeltme katmanı: _apply_corrections insan
    kararını pipeline çıktısının üstüne yazar.
  * merge_few_shot: semantic öncelik + dedup + limit.

2026-08-18 (migration 0042, WS3) — skor/deneyim/perspektif genişlemesi:
  * sentiment_score/experience_type/perspective_code duygu+kategoriden
    BAĞIMSIZ düzeltilebilir (yalnız skor düzeltmesi de geçerli).
  * patch_analysis_with_decision: kayıtlı new_score varsa AYNEN
    uygulanır (yoksa SCORE_FOR_LABEL fallback) — hem birebir hem
    anlamsal override yolunda.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_core.models import (
    AnalysisResult,
    CategoryClassification,
)
from imga_db.models import (
    Review,
    ReviewCorrection,
    ReviewDecision,
    User,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


async def _seed_review(
    admin_session: AsyncSession,
    *,
    tenant_id: UUID,
    text_value: str,
    sentiment_label: str = "POZITIF",
    primary_category: str = "kargo",
) -> UUID:
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        row = Review(
            tenant_id=tenant_id,
            text=text_value,
            text_hash=review_text_hash(text_value),
            sentiment_label=sentiment_label,
            sentiment_score=0.8,
            primary_category=primary_category,
            primary_confidence=0.7,
            automation_mode="semi_auto",
            decision=ReviewDecision.SKIPPED_THRESHOLD,
            decision_reason=None,
            ticket_id=None,
            submitted_by_user_id=None,
            batch_job_id=None,
            analyzed_at=datetime.now(UTC),
        )
        admin_session.add(row)
        await admin_session.flush()
        review_id = row.id
        admin_session.expunge(row)
    return review_id


@pytest.mark.asyncio
async def test_correct_review_updates_decision_and_records_correction(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    text_value = "Kargo guya hizliydi ama paket parcalanmis geldi, rezalet."
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value=text_value,
        sentiment_label="POZITIF",
        primary_category="musteri_hizmetleri",
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sentiment_label": "NEGATIF",
            "primary_category": "kargo",
            "reason": "İroni — müşteri aslında şikayetçi.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sentiment_label"] == "NEGATIF"
    assert body["sentiment_score"] == -0.9
    assert body["primary_category"] == "kargo"
    # Test ortamında tenant Gemini credential'ı yok → embedding yok.
    assert body["embedding_stored"] is False

    # Review satırı güncellendi + insan-kararı izi düştü.
    detail = batch_client.get(
        f"/tenants/me/reviews/{review_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    d = detail.json()
    assert d["sentiment"]["label"] == "NEGATIF"
    assert d["categorization"]["primary"] == "kargo"
    layers = [o.get("layer") for o in d["overrides_applied"]]
    assert "user_correction" in layers

    # Correction satırı: eski/yeni değerler + hash.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        correction = (
            await admin_session.execute(
                select(ReviewCorrection).where(ReviewCorrection.review_id == review_id)
            )
        ).scalar_one()
        assert correction.old_sentiment_label == "POZITIF"
        assert correction.new_sentiment_label == "NEGATIF"
        assert correction.old_category == "musteri_hizmetleri"
        assert correction.new_category == "kargo"
        assert correction.text_hash == review_text_hash(text_value)
        assert correction.embedding is None


@pytest.mark.asyncio
async def test_correct_review_validation_errors(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Dogrulama senaryolari icin nötr bir yorum metni.",
        sentiment_label="NÖTR",
        primary_category="kargo",
    )
    token = login_token(batch_client, user.email, pw, tid)

    # Değişiklik yok → 400.
    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"sentiment_label": "NÖTR", "primary_category": "kargo"},
    )
    assert r.status_code == 400

    # Bilinmeyen kategori → 400.
    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"primary_category": "boyle-bir-kategori-yok"},
    )
    assert r.status_code == 400

    # Hiç alan yok → 400.
    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_correct_review_score_only_independent_of_sentiment_category(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 — yalnız skor düzeltmesi de geçerli bir istek
    (duygu/kategori değişmeden). Review.sentiment_score kayıtlı
    new_score'a çekilir; sentiment_label/primary_category aynı kalır."""
    user, tid, pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Skor-yalniz duzeltme testi icin yorum metni.",
        sentiment_label="NEGATIF",
        primary_category="kargo",
    )
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"sentiment_score": -0.35},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sentiment_label"] == "NEGATIF"
    assert body["sentiment_score"] == -0.35
    assert body["primary_category"] == "kargo"

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        row = await admin_session.get(Review, review_id)
        assert row is not None
        assert row.sentiment_score == -0.35
        assert row.sentiment_label == "NEGATIF"
        correction = (
            await admin_session.execute(
                select(ReviewCorrection).where(ReviewCorrection.review_id == review_id)
            )
        ).scalar_one()
        assert correction.new_score == -0.35
        assert correction.new_sentiment_label == "NEGATIF"
        assert correction.new_category == "kargo"


@pytest.mark.asyncio
async def test_correct_review_category_only_after_score_correction_preserves_score(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 (bulgu düzeltmesi) — bir skor düzeltmesinden SONRA
    gelen kategori-yalnız düzeltme, mevcut ince ayarlı skoru
    SCORE_FOR_LABEL'e (KB sabiti) sıfırlamamalı. Eskiden new_score
    None olduğunda effective_score her zaman SCORE_FOR_LABEL[label]'e
    düşüyordu — etiket değişmese bile — bu da -0.35 gibi bir skoru
    -0.9'a sıçratıp kriz eşiğini yanlışlıkla aşırıyordu."""
    user, tid, pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Skor sonrasi kategori duzeltme testi icin yorum.",
        sentiment_label="NEGATIF",
        primary_category="kargo",
    )
    token = login_token(batch_client, user.email, pw, tid)

    first = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"sentiment_score": -0.35},
    )
    assert first.status_code == 200, first.text
    assert first.json()["sentiment_score"] == -0.35

    second = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"primary_category": "musteri_hizmetleri"},
    )
    assert second.status_code == 200, second.text
    body = second.json()
    # Etiket değişmedi (NEGATIF) — skor KB sabitine (-0.9) DEĞİL,
    # önceki düzeltmenin -0.35 değerine korunmalı.
    assert body["sentiment_label"] == "NEGATIF"
    assert body["primary_category"] == "musteri_hizmetleri"
    assert body["sentiment_score"] == -0.35

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        row = await admin_session.get(Review, review_id)
        assert row is not None
        assert row.sentiment_score == -0.35
        assert row.primary_category == "musteri_hizmetleri"
        # İkinci düzeltme satırının ham new_score'u None kalır (yalnız
        # kategori gönderildi) — korunan skor review satırında, KB
        # sabitinde değil.
        latest_correction = (
            await admin_session.execute(
                select(ReviewCorrection)
                .where(ReviewCorrection.review_id == review_id)
                .order_by(ReviewCorrection.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        assert latest_correction.new_score is None
        assert latest_correction.new_category == "musteri_hizmetleri"


@pytest.mark.asyncio
async def test_correct_review_experience_and_perspective(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """experience_type + perspective_code düzeltmesi Review satırına
    işlenir; perspective_code tenant'ın aktif taksonomi kodlarından
    biri olmalı (default seed'ten shipment_not_arrived kullanılıyor)."""
    user, tid, pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Deneyim ve perspektif duzeltme testi yorumu.",
    )
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "experience_type": "operasyonel",
            "perspective_code": "shipment_not_arrived",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["experience_type"] == "operasyonel"
    assert body["perspective_code"] == "shipment_not_arrived"

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        row = await admin_session.get(Review, review_id)
        assert row is not None
        assert row.experience_type == "operasyonel"
        assert row.company_perspective_code == "shipment_not_arrived"


@pytest.mark.asyncio
async def test_correct_review_invalid_experience_and_perspective(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Gecersiz deneyim/perspektif testi icin yorum.",
    )
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"experience_type": "fiziksel"},
    )
    assert r.status_code == 422  # pydantic Literal enum reddi

    r = batch_client.post(
        f"/tenants/me/reviews/{review_id}/correct",
        headers={"Authorization": f"Bearer {token}"},
        json={"perspective_code": "boyle-bir-kod-yok"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pgvector_nearest_corrections_roundtrip(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """asyncpg + pgvector gerçek yol: embedding'li correction yaz,
    cosine komşu sorgusuyla geri bul. Embedding'i NULL olan satır
    sonuçlara karışmamalı."""
    from imga_api.services.correction_store import nearest_corrections

    _user, tid, _pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Vektor arama dogrulamasi icin ornek yorum metni bir.",
    )
    base = [0.0] * 768
    base[0] = 1.0
    near = [0.0] * 768
    near[0] = 0.96
    near[1] = 0.28

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash("ornek bir"),
                review_text="Kargom cok gec geldi ve kutu ezikti.",
                old_sentiment_label="NÖTR",
                new_sentiment_label="NEGATIF",
                old_category="belirsiz",
                new_category="kargo",
                reason=None,
                embedding=base,
            )
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash("ornek iki"),
                review_text="Embeddingsiz duzeltme satiri.",
                old_sentiment_label="NÖTR",
                new_sentiment_label="POZITIF",
                old_category="belirsiz",
                new_category="urun_kalitesi",
                reason=None,
                embedding=None,
            )
        )
        await admin_session.flush()

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        neighbours = await nearest_corrections(admin_session, tid, near, k=5)
    assert len(neighbours) == 1
    assert neighbours[0].category == "kargo"
    assert neighbours[0].sentiment_label == "NEGATIF"


def test_apply_corrections_patches_matching_rows() -> None:
    from imga_api.services.correction_store import (
        CorrectedDecision,
        CorrectionStore,
    )
    from imga_api.workers.batch_analyzer import (
        UnifiedJobContext,
        _apply_corrections,
    )

    corrected_text = "Bu yorum daha once insan tarafindan duzeltildi."
    other_text = "Bu yorumun duzeltmesi yok, pipeline karari kalmali."
    store = CorrectionStore(
        tenant_id=UUID(int=1),
        exact={
            review_text_hash(corrected_text): CorrectedDecision(
                sentiment_label="NEGATIF", category="iade"
            )
        },
    )
    ctx = UnifiedJobContext(
        engine=None,  # type: ignore[arg-type] — patch yolu motoru kullanmaz
        available_categories=["kargo", "iade"],
        store=store,
        keys=[],
    )

    def _analysis(text_value: str) -> AnalysisResult:
        return AnalysisResult(
            text=text_value,
            sentiment_label="POZITIF",
            sentiment_score=0.7,
            overrides_applied=[],
            summary=None,
            customer_perspective=None,
            company_perspective=None,
            risk_class="POZITIF",
            sla_detected=None,
            categorization=CategoryClassification(primary="kargo", primary_confidence=0.6),
        )

    analyses = [_analysis(corrected_text), _analysis(other_text)]
    # 2026-08-18 — _apply_corrections artık (analyses, correction_overrides)
    # tuple'ı döner (WS2/batch_analyzer.py imza genişlemesi); bu test
    # yalnız yeni imzaya uyarlanır, mevcut assertion'lar değişmez +
    # ikinci elemanı da doğrular (aşağıda).
    patched, overrides = _apply_corrections(
        analyses, [corrected_text, other_text], ctx
    )

    assert patched[0].sentiment_label == "NEGATIF"
    assert patched[0].sentiment_score == -0.9
    assert patched[0].categorization is not None
    assert patched[0].categorization.primary == "iade"
    assert patched[0].overrides_applied[-1].layer == "user_correction_kb"
    # Eşleşmeyen satır olduğu gibi kalır.
    assert patched[1].sentiment_label == "POZITIF"
    assert patched[1].overrides_applied == []
    # 2026-08-18 (B3 sözleşme notu) — ikinci dönüş değeri, satır
    # sırasına göre UYGULANAN CorrectedDecision'ı taşır. batch_analyzer
    # ._process_chunk'ın per-satır döngüsü experience_type/
    # perspective_code'u (AnalysisResult'a giremeyen iki alan) bu
    # listeden okuyup uygular — bkz. workers/test_batch_quality.py'nin
    # dinamik kategori/kalite testleriyle aynı dalga.
    assert overrides[0] is not None
    assert overrides[0].sentiment_label == "NEGATIF"
    assert overrides[1] is None


def test_apply_corrections_overrides_carry_experience_and_perspective() -> None:
    """Aynı ikinci dönüş değeri experience_type/perspective_code'u da
    taşımalı — batch_analyzer._process_chunk bunları AnalysisResult
    DIŞINDA, decision nesnesinden doğrudan okuyor (bkz.
    CorrectedDecision docstring'i)."""
    from imga_api.services.correction_store import (
        CorrectedDecision,
        CorrectionStore,
    )
    from imga_api.workers.batch_analyzer import (
        UnifiedJobContext,
        _apply_corrections,
    )

    corrected_text = "Deneyim ve perspektif tasiyan duzeltme testi."
    store = CorrectionStore(
        tenant_id=UUID(int=1),
        exact={
            review_text_hash(corrected_text): CorrectedDecision(
                sentiment_label="NEGATIF",
                category="kargo",
                experience_type="operasyonel",
                perspective_code="shipment_not_arrived",
            )
        },
    )
    ctx = UnifiedJobContext(
        engine=None,  # type: ignore[arg-type]
        available_categories=["kargo"],
        store=store,
        keys=[],
    )
    analysis = AnalysisResult(
        text=corrected_text,
        sentiment_label="POZITIF",
        sentiment_score=0.7,
        overrides_applied=[],
        categorization=CategoryClassification(primary="kargo", primary_confidence=0.6),
    )
    _patched, overrides = _apply_corrections(
        [analysis], [corrected_text], ctx
    )
    assert overrides[0] is not None
    assert overrides[0].experience_type == "operasyonel"
    assert overrides[0].perspective_code == "shipment_not_arrived"


def test_patch_analysis_with_decision_applies_recorded_score() -> None:
    """2026-08-18 (migration 0042) — kayıtlı new_score varsa AYNEN
    uygulanır (SCORE_FOR_LABEL fallback'ine düşmez). Hem birebir hem
    anlamsal override yolu aynı fonksiyondan geçtiği için tek unit
    test kontratı ikisini de kapsar."""
    from imga_api.services.correction_store import (
        CorrectedDecision,
        patch_analysis_with_decision,
    )

    analysis = AnalysisResult(
        text="skor testi",
        sentiment_label="POZITIF",
        sentiment_score=0.7,
        overrides_applied=[],
        categorization=CategoryClassification(primary="kargo", primary_confidence=0.6),
    )
    # new_score kayıtlı DEĞİL — eski davranış: SCORE_FOR_LABEL fallback.
    decision_no_score = CorrectedDecision(sentiment_label="NEGATIF", category="iade")
    patched_fallback = patch_analysis_with_decision(
        analysis, decision_no_score, layer="user_correction_kb", detail_prefix="t"
    )
    assert patched_fallback.sentiment_score == -0.9  # KB_NEGATIVE_SCORE

    # new_score kayıtlı — AYNEN uygulanır, KB sabitine düşmez.
    decision_with_score = CorrectedDecision(sentiment_label="NEGATIF", category="iade", score=-0.42)
    patched_scored = patch_analysis_with_decision(
        analysis, decision_with_score, layer="user_correction_kb", detail_prefix="t"
    )
    assert patched_scored.sentiment_score == -0.42
    assert "skor=-0.42" in patched_scored.overrides_applied[-1].detail


@pytest.mark.asyncio
async def test_semantic_override_lookup_threshold(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Sprint 11.3 — anlamsal doğrudan override: ≤0.05 cosine
    mesafedeki sorgu kararı alır; uzak sorgu None döner."""
    from imga_api.services.correction_store import semantic_override_lookup

    _user, tid, _pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Anlamsal override esik testi icin yorum metni.",
    )
    base = [0.0] * 768
    base[0] = 1.0
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash("anlamsal bir"),
                review_text="Kargo cok gecikti, kutu hasarli.",
                old_sentiment_label="NÖTR",
                new_sentiment_label="NEGATIF",
                old_category="belirsiz",
                new_category="kargo",
                reason=None,
                embedding=base,
                # 2026-08-18 — semantic yolun new_score/new_experience/
                # new_perspective'i de taşıdığını doğrular.
                new_score=-0.55,
                new_experience="operasyonel",
                new_perspective="shipment_not_arrived",
            )
        )
        await admin_session.flush()

    near_identical = list(base)  # distance 0
    far = [0.0] * 768
    far[1] = 1.0  # ortogonal — distance 1.0

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        hit = await semantic_override_lookup(admin_session, tid, near_identical)
        miss = await semantic_override_lookup(admin_session, tid, far)
    assert hit is not None
    assert hit.sentiment_label == "NEGATIF"
    assert hit.category == "kargo"
    assert hit.score == -0.55
    assert hit.experience_type == "operasyonel"
    assert hit.perspective_code == "shipment_not_arrived"
    assert miss is None


@pytest.mark.asyncio
async def test_load_correction_store_exact_lookup_carries_new_score(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 (KRİTİK, migration 0042) — birebir yolun ana
    tüketicisi ``load_correction_store``: text_hash başına yüklenen
    ``CorrectedDecision`` skor/deneyim/perspektif düzeltmesini de
    taşımalı (batch worker'ın exact_lookup() aracılığıyla okuduğu
    yol — bu doğrulanmadan KRİTİK madde eksik kalır)."""
    from imga_api.services.correction_store import load_correction_store

    _user, tid, _pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value="Birebir depo testi icin yorum metni.",
    )
    text_hash = review_text_hash("Birebir depo testi icin yorum metni.")
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=text_hash,
                review_text="Birebir depo testi icin yorum metni.",
                old_sentiment_label="NÖTR",
                new_sentiment_label="NEGATIF",
                old_category="belirsiz",
                new_category="kargo",
                reason=None,
                new_score=-0.2,
                new_experience="dijital",
                new_perspective="shipment_not_arrived",
            )
        )
        await admin_session.flush()

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        store = await load_correction_store(admin_session, tid)

    decision = store.exact_lookup(text_hash)
    assert decision is not None
    assert decision.sentiment_label == "NEGATIF"
    assert decision.category == "kargo"
    assert decision.score == -0.2
    assert decision.experience_type == "dijital"
    assert decision.perspective_code == "shipment_not_arrived"


@pytest.mark.asyncio
async def test_manual_analyze_corrections_exact_patch(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Manuel analiz yolu: birebir düzeltme analiz sonucunu ezer.

    2026-08-18 (bulgu FX3) — ``tenant_analyze.py`` artık tek bir
    ``_apply_manual_corrections`` monolitini değil, ayrı fazlara
    bölünmüş parçaları çağırıyor (bkz. o dosyanın modül docstring'i:
    Faz 1 kısa okuma tx'i → Faz 2 transaction dışı embed → Faz 3 kısa
    okuma tx'i). Bu test route'un Faz 1'de yaptığı ``latest_exact_
    correction`` okumasını + route'un bellek-içi (I/O'suz)
    ``_apply_correction_priority``'sini AYNI SIRAYLA çağırır."""
    from imga_api.routes.tenant_analyze import _apply_correction_priority
    from imga_api.services.correction_store import latest_exact_correction

    _user, tid, _pw = semi_auto_tenant
    corrected_text = "Manuel analiz birebir duzeltme testi yorumu."
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value=corrected_text,
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash(corrected_text),
                review_text=corrected_text,
                old_sentiment_label="POZITIF",
                new_sentiment_label="NEGATIF",
                old_category="kargo",
                new_category="iade",
                reason=None,
                embedding=None,
            )
        )
        await admin_session.flush()

    analysis = AnalysisResult(
        text=corrected_text,
        sentiment_label="POZITIF",
        sentiment_score=0.8,
        overrides_applied=[],
        categorization=CategoryClassification(primary="kargo", primary_confidence=0.7),
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        exact = await latest_exact_correction(
            admin_session, tid, review_text_hash(corrected_text)
        )
    patched, decision = _apply_correction_priority(
        analysis, exact=exact, semantic=None
    )
    assert patched.sentiment_label == "NEGATIF"
    assert patched.categorization is not None
    assert patched.categorization.primary == "iade"
    assert patched.overrides_applied[-1].layer == "user_correction_kb"
    # 2026-08-18 (WS3) — decision nesnesi de dönüyor, çağıran
    # (route) experience_type/perspective_code'u AnalysisResult
    # dışında buradan okuyup uygulamalı; bu düzeltme kaydında ikisi
    # de NULL (yalnız sentiment/category verildi).
    assert decision is not None
    assert decision.experience_type is None
    assert decision.perspective_code is None


@pytest.mark.asyncio
async def test_manual_analyze_corrections_exact_patch_applies_new_score(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 — manuel analiz birebir yolu: review_corrections'a
    kayıtlı new_score, SCORE_FOR_LABEL fallback'i yerine AYNEN
    uygulanır. Yeni analizde düzeltme deseni tam taşınmalı — skor
    düzeltmesi ilk tekrar karşılaşmada ölmemeli."""
    from imga_api.routes.tenant_analyze import _apply_correction_priority
    from imga_api.services.correction_store import latest_exact_correction

    _user, tid, _pw = semi_auto_tenant
    corrected_text = "Manuel analiz skor duzeltme testi yorumu."
    review_id = await _seed_review(
        admin_session,
        tenant_id=tid,
        text_value=corrected_text,
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash(corrected_text),
                review_text=corrected_text,
                old_sentiment_label="POZITIF",
                new_sentiment_label="NEGATIF",
                old_category="kargo",
                new_category="iade",
                reason=None,
                embedding=None,
                new_score=-0.2,
                new_experience="dijital",
                new_perspective="shipment_not_arrived",
            )
        )
        await admin_session.flush()

    analysis = AnalysisResult(
        text=corrected_text,
        sentiment_label="POZITIF",
        sentiment_score=0.8,
        overrides_applied=[],
        categorization=CategoryClassification(primary="kargo", primary_confidence=0.7),
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        exact = await latest_exact_correction(
            admin_session, tid, review_text_hash(corrected_text)
        )
    patched, decision = _apply_correction_priority(
        analysis, exact=exact, semantic=None
    )
    assert patched.sentiment_label == "NEGATIF"
    # SCORE_FOR_LABEL["NEGATIF"] (-0.9) DEĞİL — kayıtlı new_score.
    assert patched.sentiment_score == -0.2
    assert patched.categorization is not None
    assert patched.categorization.primary == "iade"
    detail = patched.overrides_applied[-1].detail or ""
    assert "skor=-0.20" in detail
    assert "deneyim=dijital" in detail
    assert "perspektif=shipment_not_arrived" in detail
    # 2026-08-18 (WS3, B3 sözleşme notu) — deneyim/perspektif
    # AnalysisResult'a giremiyor (pydantic extra=forbid); route bu
    # ikisini decision nesnesinden DOĞRUDAN okuyup Review satırına
    # kendisi uygulamalı — decision'ın taşıdığını burada doğrula.
    assert decision is not None
    assert decision.experience_type == "dijital"
    assert decision.perspective_code == "shipment_not_arrived"


@pytest.mark.asyncio
async def test_manual_analyze_corrections_semantic_works_without_tenant_keys(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-08-18 (B3 sözleşme notu, B4 düzeltmesi, FX3 yeniden
    yapılandırması) — eskiden ``if not keys: return`` erken çıkışı,
    tenant'ın Gemini anahtarı yokken ``embed_text``'e HİÇ
    ULAŞILMASINI engelliyordu; bu da ``IMGA_EMBEDDING_FALLBACK_KEY``
    platform yedeğinin bu yolda asla devreye giremeyeceği anlamına
    geliyordu (``embed_text`` zaten boş ``keys`` ile çağrılsa fallback
    kararını kendi verir — bkz. ``embedding_service._fallback_keys``).

    Bu test route'un Faz 2 (transaction dışı, tek embed çağrısı) + Faz
    3 (anlamsal okuma) adımlarını doğrudan tekrarlar: ``latest_exact_
    correction`` eşleşmez (birebir yolu DEĞİL, anlamsal yolu tetikler)
    → ``embed_text`` boş ``keys`` ile çağrılır (stub'lanmış) →
    ``semantic_override_lookup`` kararı bulur → ``_apply_correction_
    priority`` bunu uygular."""
    import imga_api.services.embedding_service as embedding_service
    from imga_api.routes.tenant_analyze import _apply_correction_priority
    from imga_api.services.correction_store import (
        latest_exact_correction,
        semantic_override_lookup,
    )

    _user, tid, _pw = semi_auto_tenant
    corrected_text = "Fallback anahtar testi icin yorum metni burada."
    review_id = await _seed_review(
        admin_session, tenant_id=tid, text_value=corrected_text
    )
    target_vector = [0.0] * 768
    target_vector[10] = 1.0
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                # Bilinçli farklı hash — birebir yolu DEĞİL, anlamsal
                # yolu tetiklemek istiyoruz.
                text_hash=review_text_hash("baska bir metin"),
                review_text="Kargom cok gec geldi.",
                old_sentiment_label="NÖTR",
                new_sentiment_label="NEGATIF",
                old_category="belirsiz",
                new_category="kargo",
                reason=None,
                embedding=target_vector,
            )
        )
        await admin_session.flush()

    embed_calls: list[list[object]] = []

    async def _stub_embed_text(_text: str, keys: list[object]) -> list[float]:
        embed_calls.append(keys)
        near = list(target_vector)
        near[11] = 0.05
        return near

    monkeypatch.setattr(embedding_service, "embed_text", _stub_embed_text)

    analysis = AnalysisResult(
        text=corrected_text,
        sentiment_label="POZITIF",
        sentiment_score=0.8,
        overrides_applied=[],
        categorization=CategoryClassification(primary="kargo", primary_confidence=0.7),
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        exact = await latest_exact_correction(
            admin_session, tid, review_text_hash(corrected_text)
        )
    assert exact is None

    # Faz 2 — route'un yaptığı gibi boş ``embedding_keys`` ile.
    vector = await embedding_service.embed_text(corrected_text, [])

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        semantic_decision = await semantic_override_lookup(admin_session, tid, vector)

    patched, decision = _apply_correction_priority(
        analysis, exact=None, semantic=semantic_decision
    )

    # Erken çıkış kaldırıldı: embed_text boş keys ile de ÇAĞRILDI.
    assert embed_calls == [[]]
    assert decision is not None
    assert patched.sentiment_label == "NEGATIF"


@pytest.mark.asyncio
async def test_load_recent_correction_examples_returns_recent_rows(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """2026-08-18 (bulgu FX3) — ``_load_recent_correction_examples``
    Faz 1'in few-shot okuma adımı (eski ``_manual_few_shot``'un
    okuma-yalnız parçası); tenant'ın son düzeltmelerini
    ``CorrectionExample`` listesine çevirir."""
    from imga_api.routes.tenant_analyze import _load_recent_correction_examples

    _user, tid, _pw = semi_auto_tenant
    review_id = await _seed_review(
        admin_session, tenant_id=tid, text_value="ilk duzeltme metni burada"
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash("ilk duzeltme metni burada"),
                review_text="Kargo cok gec geldi, musteri sikayetci.",
                old_sentiment_label="NÖTR",
                new_sentiment_label="NEGATIF",
                old_category="belirsiz",
                new_category="kargo",
                reason=None,
            )
        )
        await admin_session.flush()

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        recent = await _load_recent_correction_examples(admin_session, tid)

    assert len(recent) == 1
    assert recent[0].category == "kargo"
    assert recent[0].sentiment_label == "NEGATIF"


@pytest.mark.asyncio
async def test_load_recent_correction_examples_empty_without_any_corrections(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenant'ta hiç düzeltme yoksa boş liste — route bu durumda
    ``need_vector`` hesabına ``bool(recent)=False`` katar (embed API'sine
    dokunmadan atlanabilir tek şart hâline gelir)."""
    from imga_api.routes.tenant_analyze import _load_recent_correction_examples

    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        recent = await _load_recent_correction_examples(admin_session, tid)
    assert recent == []


def test_apply_correction_priority_exact_beats_semantic() -> None:
    """2026-08-18 (bulgu FX3) — ``_apply_correction_priority`` saf
    fonksiyon: birebir (``exact``) her zaman anlamsal (``semantic``)
    düzeltmeden önceliklidir, ikisi de yoksa analiz olduğu gibi kalır."""
    from imga_api.routes.tenant_analyze import _apply_correction_priority
    from imga_api.services.correction_store import CorrectedDecision

    analysis = AnalysisResult(
        text="oncelik testi",
        sentiment_label="POZITIF",
        sentiment_score=0.7,
        overrides_applied=[],
        categorization=CategoryClassification(primary="kargo", primary_confidence=0.6),
    )
    exact = CorrectedDecision(sentiment_label="NEGATIF", category="iade")
    semantic = CorrectedDecision(sentiment_label="NÖTR", category="belirsiz")

    both_patched, both_decision = _apply_correction_priority(
        analysis, exact=exact, semantic=semantic
    )
    assert both_decision is exact
    assert both_patched.sentiment_label == "NEGATIF"

    only_semantic_patched, only_semantic_decision = _apply_correction_priority(
        analysis, exact=None, semantic=semantic
    )
    assert only_semantic_decision is semantic
    assert only_semantic_patched.sentiment_label == "NÖTR"
    assert (
        only_semantic_patched.overrides_applied[-1].layer
        == "user_correction_semantic"
    )

    neither_patched, neither_decision = _apply_correction_priority(
        analysis, exact=None, semantic=None
    )
    assert neither_decision is None
    assert neither_patched is analysis


def test_resolve_experience_and_perspective_correction_beats_llm_sink() -> None:
    """2026-08-18 (bulgu FX3) — ``_resolve_experience_and_perspective``:
    insan düzeltmesi LLM'in KENDİ (birleşik motor perspective_sink/
    experience_sink) tahmininin önüne geçer; korrection yoksa LLM'in
    tahmini kullanılır (yeni davranış — eskiden bu route'ta LLM'in
    kendi kararı hiç okunmuyordu). İkisi de yoksa None (record_and_
    decide'ın heuristiğine/NULL'a düşülür)."""
    from imga_api.routes.tenant_analyze import _resolve_experience_and_perspective
    from imga_api.services.correction_store import CorrectedDecision

    labels = {"shipment_not_arrived": "Kargo Gelmedi", "wrong_item": "Yanlış Ürün"}

    # 1) Düzeltme VE LLM ikisi de dolu — düzeltme kazanır.
    correction = CorrectedDecision(
        sentiment_label="NEGATIF",
        category="kargo",
        experience_type="operasyonel",
        perspective_code="shipment_not_arrived",
    )
    experience, perspective_override = _resolve_experience_and_perspective(
        correction_decision=correction,
        llm_perspective_code="wrong_item",
        llm_experience_type="dijital",
        perspective_labels=labels,
    )
    assert experience == "operasyonel"
    assert perspective_override == ("shipment_not_arrived", "Kargo Gelmedi")

    # 2) Düzeltme YOK — LLM'in KENDİ tahmini uygulanır (bulgu — eskiden
    # bu çöpe gidiyordu).
    experience, perspective_override = _resolve_experience_and_perspective(
        correction_decision=None,
        llm_perspective_code="wrong_item",
        llm_experience_type="dijital",
        perspective_labels=labels,
    )
    assert experience == "dijital"
    assert perspective_override == ("wrong_item", "Yanlış Ürün")

    # 3) LLM'in perspektif kodu tenant'ın taksonomisinde YOK — heuristiğe
    # düşülsün diye override None kalmalı.
    experience, perspective_override = _resolve_experience_and_perspective(
        correction_decision=None,
        llm_perspective_code="bilinmeyen_kod",
        llm_experience_type=None,
        perspective_labels=labels,
    )
    assert experience is None
    assert perspective_override is None

    # 4) İkisi de yok — tamamen None (record_and_decide kendi
    # heuristiğine/NULL'a düşer).
    experience, perspective_override = _resolve_experience_and_perspective(
        correction_decision=None,
        llm_perspective_code=None,
        llm_experience_type=None,
        perspective_labels=labels,
    )
    assert experience is None
    assert perspective_override is None


@pytest.mark.asyncio
async def test_classify_manual_analysis_falls_back_to_classic_without_unified() -> None:
    """``unified=None`` — klasik BERT+keyword/LLM hibrit yol (mevcut
    davranış) hiç değişmeden çalışır."""
    from imga_core import AnalysisPipeline, KeywordCategoryClassifier

    from imga_api.routes.tenant_analyze import _classify_manual_analysis
    from tests.batch_helpers import StubBatchAnalyzer

    pipeline = AnalysisPipeline(
        analyzer=StubBatchAnalyzer(), classifier=KeywordCategoryClassifier()
    )
    (
        analysis,
        llm_used,
        _model,
        _provider,
        llm_perspective,
        llm_experience,
    ) = await _classify_manual_analysis("test metni", pipeline, None, ())
    assert llm_used is False
    assert analysis.text == "test metni"
    assert llm_perspective is None
    assert llm_experience is None


@pytest.mark.asyncio
async def test_classify_manual_analysis_uses_unified_engine_with_few_shot() -> None:
    """2026-08-18 (WS3) — ``unified`` aktifken sınıflandırma birleşik
    motordan gelir; ``few_shot`` argümanı motora AYNEN iletilir
    (bugüne kadar manuel yolda hiç olmayan katman-2 kapsaması).

    2026-08-18 (bulgu FX3) — LLM'in KENDİ perspektif/deneyim tahmini
    (``UnifiedPrediction.perspective_code``/``experience_type``) artık
    dönüş değerinde de taşınır (``perspective_sink``/``experience_sink``
    out-param'ları ``AnalysisPipeline.analyze_batch_unified_async``
    tarafından dolduruluyor — bkz. o fonksiyonun docstring'i); eskiden
    bu route bu iki alanı hiç okumuyordu."""
    from imga_core import AnalysisPipeline, KeywordCategoryClassifier
    from imga_core.llm.unified_classifier import (
        FewShotExample,
        UnifiedBatchStats,
        UnifiedPrediction,
    )

    from imga_api.routes.tenant_analyze import (
        _classify_manual_analysis,
        _ManualUnifiedContext,
    )
    from tests.batch_helpers import StubBatchAnalyzer

    captured: dict[str, object] = {}

    class _FakeEngine:
        model_name = "fake-unified-model"
        provider = "gemini"

        async def classify_unified_batch_async(
            self,
            texts: list[str],
            *,
            available_categories: list[str],
            few_shot: tuple[FewShotExample, ...] = (),
            perspective_options: object = None,
            category_descriptions: dict[str, str] | None = None,
        ) -> tuple[list[UnifiedPrediction], UnifiedBatchStats]:
            captured["few_shot"] = few_shot
            captured["available_categories"] = available_categories
            return (
                [
                    UnifiedPrediction(
                        sentiment_label="NEGATIF",
                        sentiment_score=-0.6,
                        category="kargo",
                        category_confidence=0.9,
                        perspective_code="shipment_not_arrived",
                        experience_type="operasyonel",
                    )
                    for _ in texts
                ],
                UnifiedBatchStats(),
            )

    pipeline = AnalysisPipeline(
        analyzer=StubBatchAnalyzer(), classifier=KeywordCategoryClassifier()
    )
    unified = _ManualUnifiedContext(
        engine=_FakeEngine(),  # type: ignore[arg-type]
        available_categories=["kargo", "belirsiz"],
        perspective_options={},
        category_descriptions={},
        perspective_labels={},
        embedding_keys=[],
    )
    few_shot = (
        FewShotExample(
            text="ornek", sentiment_label="NEGATIF", category="kargo", reason=None
        ),
    )
    (
        analysis,
        llm_used,
        model_name,
        provider,
        llm_perspective,
        llm_experience,
    ) = await _classify_manual_analysis(
        "kargom gelmedi", pipeline, unified, few_shot
    )
    assert llm_used is True
    assert model_name == "fake-unified-model"
    assert provider == "gemini"
    assert analysis.sentiment_label == "NEGATIF"
    assert analysis.categorization is not None
    assert analysis.categorization.primary == "kargo"
    assert captured["few_shot"] == few_shot
    assert captured["available_categories"] == ["kargo", "belirsiz"]
    # 2026-08-18 (bulgu FX3) — sink'ler LLM'in KENDİ tahminini taşır.
    assert llm_perspective == "shipment_not_arrived"
    assert llm_experience == "operasyonel"


@pytest.mark.asyncio
async def test_classify_manual_analysis_timeout_falls_back_to_classic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-08-18 (bulgu FX3) — birleşik motor ``_MANUAL_UNIFIED_
    TIMEOUT_SECONDS`` aşarsa (yavaş/takılı sağlayıcı), motorun kendi
    4×240s + 5/15/30s rotasyon merdivenini beklemeden klasik yola
    düşülür. ``asyncio.wait_for`` iptal edeceği için motor asla
    tamamlanmaz — ``llm_used=False`` + sink'ler None ile klasik
    pipeline'ın sonucu döner."""
    from imga_core import AnalysisPipeline, KeywordCategoryClassifier
    from imga_core.llm.unified_classifier import (
        FewShotExample,
        UnifiedBatchStats,
        UnifiedPrediction,
    )

    import imga_api.routes.tenant_analyze as tenant_analyze_module
    from imga_api.routes.tenant_analyze import (
        _classify_manual_analysis,
        _ManualUnifiedContext,
    )
    from imga_api.services.executive_briefing_service import DEFAULT_MODEL_NAME
    from tests.batch_helpers import StubBatchAnalyzer

    # Testin gerçek 60 saniye beklememesi için tavan çok kısaltılır —
    # modül seviyesinde okunur (fonksiyon gövdesinde, parametre
    # varsayılanı DEĞİL) diye monkeypatch işe yarıyor (bkz. modülün
    # kendi yorum notu).
    monkeypatch.setattr(
        tenant_analyze_module, "_MANUAL_UNIFIED_TIMEOUT_SECONDS", 0.05
    )

    class _SlowEngine:
        model_name = "slow-unified-model"
        provider = "openrouter"

        async def classify_unified_batch_async(
            self,
            texts: list[str],
            *,
            available_categories: list[str],
            few_shot: tuple[FewShotExample, ...] = (),
            perspective_options: object = None,
            category_descriptions: dict[str, str] | None = None,
        ) -> tuple[list[UnifiedPrediction], UnifiedBatchStats]:
            # Motorun gerçek rotasyon merdiveni bu kadar uzun sürebilir
            # (4x240s + uykular) — burada yalnız kısaltılmış tavanı
            # geçecek kadar uyutuluyor.
            import asyncio as _asyncio

            await _asyncio.sleep(1.0)
            return (
                [
                    UnifiedPrediction(
                        sentiment_label="NEGATIF",
                        sentiment_score=-0.9,
                        category="kargo",
                        category_confidence=0.9,
                    )
                    for _ in texts
                ],
                UnifiedBatchStats(),
            )

    pipeline = AnalysisPipeline(
        analyzer=StubBatchAnalyzer(), classifier=KeywordCategoryClassifier()
    )
    unified = _ManualUnifiedContext(
        engine=_SlowEngine(),  # type: ignore[arg-type]
        available_categories=["kargo", "belirsiz"],
        perspective_options={},
        category_descriptions={},
        perspective_labels={},
        embedding_keys=[],
    )
    (
        _analysis,
        llm_used,
        model_name,
        provider,
        llm_perspective,
        llm_experience,
    ) = await _classify_manual_analysis("kargom gelmedi", pipeline, unified, ())
    # Motorun sonucu (NEGATIF/kargo) DEĞİL — klasik yolun sonucu.
    assert llm_used is False
    assert model_name == DEFAULT_MODEL_NAME
    assert provider == "gemini"
    assert llm_perspective is None
    assert llm_experience is None


@pytest.mark.asyncio
async def test_few_shot_for_chunk_embeds_full_chunk_not_first_64(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-08-18 (WS3 kapsam düzeltmesi) — eskiden ``_few_shot_for_chunk``
    yalnız chunk'ın ilk 64 satırını embed ederdi (``sample =
    texts[:64]``); 200 satırlık varsayılan chunk boyutunda 65. satır
    ve sonrası centroid'i hiç etkilemiyor, satır-bazlı anlamsal
    override'ı (``semantic_hits``) hiç göremiyordu.

    Bu test 70 satırlık bir chunk kurar; YALNIZ index 64'teki satır
    (eski ``texts[:64]`` örneklemesinin kapsamadığı ilk satır)
    tenant'ın kayıtlı bir düzeltmesine neredeyse birebir (cosine
    mesafe eşik altı, ``SEMANTIC_OVERRIDE_MAX_DISTANCE=0.05``) — stub
    ``embed_texts`` bunu deterministik üretir, kalan 69 satır uzak bir
    vektöre gider. Düzeltme öncesi kodda bu satır asla embed
    edilmediği için ``semantic_hits`` boş kalırdı; düzeltmeden sonra
    64 anahtarı dolu olmalı."""
    import imga_api.services.embedding_service as embedding_service
    from imga_api.services.correction_store import (
        CorrectionExample,
        CorrectionStore,
    )
    from imga_api.workers.batch_analyzer import (
        UnifiedJobContext,
        WorkerContext,
        _few_shot_for_chunk,
        build_worker_context,
    )

    _user, tid, _pw = semi_auto_tenant

    target_vector = [0.0] * 768
    target_vector[5] = 1.0
    corrected_text = "Kayitli duzeltme metni tam burada duruyor."
    review_id = await _seed_review(
        admin_session, tenant_id=tid, text_value=corrected_text
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        admin_session.add(
            ReviewCorrection(
                tenant_id=tid,
                review_id=review_id,
                text_hash=review_text_hash(corrected_text),
                review_text=corrected_text,
                old_sentiment_label="NÖTR",
                new_sentiment_label="NEGATIF",
                old_category="belirsiz",
                new_category="kargo",
                reason=None,
                embedding=target_vector,
            )
        )
        await admin_session.flush()

    texts = [f"alakasiz metin numara {i}" for i in range(70)]
    # Eski kodun ASLA embed etmediği ilk satır (0-index'te 64).
    target_index = 64

    async def _stub_embed_texts(
        batch_texts: list[str], _keys: object
    ) -> list[list[float]]:
        vectors = []
        for t in batch_texts:
            if texts.index(t) == target_index:
                near = list(target_vector)
                near[6] = 0.05  # cosine mesafesi eşiğin (0.05) İÇİNDE
                vectors.append(near)
            else:
                far = [0.0] * 768
                far[300] = 1.0  # target_vector'e dik — eşiğin dışında
                vectors.append(far)
        return vectors

    monkeypatch.setattr(embedding_service, "embed_texts", _stub_embed_texts)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context: WorkerContext = await build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    try:
        store = CorrectionStore(
            tenant_id=tid,
            exact={},
            recent_examples=[
                CorrectionExample(
                    text=corrected_text,
                    sentiment_label="NEGATIF",
                    category="kargo",
                    reason=None,
                )
            ],
            has_embeddings=True,
        )
        unified_ctx = UnifiedJobContext(
            engine=None,  # type: ignore[arg-type] — bu test motoru çağırmıyor
            available_categories=["kargo"],
            store=store,
            keys=[],
        )
        _few_shot, semantic_hits = await _few_shot_for_chunk(
            unified_ctx, texts, context, tid
        )
    finally:
        await context.dispose()

    assert target_index in semantic_hits
    assert semantic_hits[target_index].category == "kargo"
    assert semantic_hits[target_index].sentiment_label == "NEGATIF"
    # Uzak satırlar (ör. ilk satır) override ALMAMALI.
    assert 0 not in semantic_hits


def test_merge_few_shot_prioritises_semantic_and_dedupes() -> None:
    from imga_api.services.correction_store import (
        CorrectionExample,
        merge_few_shot,
    )

    def example(text_value: str) -> CorrectionExample:
        return CorrectionExample(
            text=text_value,
            sentiment_label="NEGATIF",
            category="kargo",
            reason=None,
        )

    semantic = [example("anlamsal bir"), example("ortak metin")]
    recent = [example("ortak metin"), example("guncel bir"), example("guncel iki")]
    merged = merge_few_shot(recent, semantic, limit=4)
    texts = [m.text for m in merged]
    assert texts == ["anlamsal bir", "ortak metin", "guncel bir", "guncel iki"]
