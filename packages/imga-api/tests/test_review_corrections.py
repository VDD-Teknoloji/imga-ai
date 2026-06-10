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
    text_value = (
        "Kargo guya hizliydi ama paket parcalanmis geldi, rezalet."
    )
    review_id = await _seed_review(
        admin_session, tenant_id=tid, text_value=text_value,
        sentiment_label="POZITIF", primary_category="musteri_hizmetleri",
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
                select(ReviewCorrection).where(
                    ReviewCorrection.review_id == review_id
                )
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
        admin_session, tenant_id=tid,
        text_value="Dogrulama senaryolari icin nötr bir yorum metni.",
        sentiment_label="NÖTR", primary_category="kargo",
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
        admin_session, tenant_id=tid,
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
        neighbours = await nearest_corrections(
            admin_session, tid, near, k=5
        )
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
            categorization=CategoryClassification(
                primary="kargo", primary_confidence=0.6
            ),
        )

    analyses = [_analysis(corrected_text), _analysis(other_text)]
    patched = _apply_corrections(
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
        admin_session, tenant_id=tid,
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
    assert miss is None


@pytest.mark.asyncio
async def test_manual_analyze_corrections_exact_patch(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Manuel analiz yolu: birebir düzeltme analiz sonucunu ezer
    (embedding'siz — tenant'ın Gemini key'i yokken de çalışır)."""
    from imga_api.routes.tenant_analyze import _apply_manual_corrections

    _user, tid, _pw = semi_auto_tenant
    corrected_text = "Manuel analiz birebir duzeltme testi yorumu."
    review_id = await _seed_review(
        admin_session, tenant_id=tid, text_value=corrected_text,
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
        categorization=CategoryClassification(
            primary="kargo", primary_confidence=0.7
        ),
    )
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        patched = await _apply_manual_corrections(
            admin_session, tid, corrected_text, analysis
        )
    assert patched.sentiment_label == "NEGATIF"
    assert patched.categorization is not None
    assert patched.categorization.primary == "iade"
    assert patched.overrides_applied[-1].layer == "user_correction_kb"


def test_merge_few_shot_prioritises_semantic_and_dedupes() -> None:
    from imga_api.services.correction_store import (
        CorrectionExample,
        merge_few_shot,
    )

    def example(text_value: str) -> CorrectionExample:
        return CorrectionExample(
            text=text_value, sentiment_label="NEGATIF",
            category="kargo", reason=None,
        )

    semantic = [example("anlamsal bir"), example("ortak metin")]
    recent = [example("ortak metin"), example("guncel bir"), example("guncel iki")]
    merged = merge_few_shot(recent, semantic, limit=4)
    texts = [m.text for m in merged]
    assert texts == ["anlamsal bir", "ortak metin", "guncel bir", "guncel iki"]
