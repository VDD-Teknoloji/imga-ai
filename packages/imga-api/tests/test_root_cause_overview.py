"""``GET /tenants/me/insights/root-cause/overview`` + the post-batch
root-cause auto-generation task (``workers.arq_worker.generate_root_causes_task``).

Sibling of ``test_root_cause.py`` (drill-down GET/POST); this file
covers the summary card list that drives the "no click required" view
and the background job that keeps it warm after every batch. Own
local seeding/payload helpers per that file's file-ownership-split
convention — no cross-import between the two test modules.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_db.models import Review, ReviewDecision, RootCauseAnalysis, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import set_redis_client
from tests.batch_helpers import login_token

_OVERVIEW_ENDPOINT = "/tenants/me/insights/root-cause/overview"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis_client() -> Any:
    """In-process Redis double, installed as the module singleton. Same
    pattern as ``test_root_cause.py``'s fixture of the same name (own
    copy per this file's file-ownership-split convention — no cross-
    import between the two test modules)."""
    import fakeredis.aioredis as fakeredis_async

    fake = fakeredis_async.FakeRedis(decode_responses=False)
    set_redis_client(fake)
    yield fake
    set_redis_client(None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(summary: str = "Kargo statüsü yanlış gösteriliyor.") -> dict[str, Any]:
    return {
        "summary": summary,
        "root_causes": [
            {
                "title": "Uygulama statüyü yanlış gösteriyor",
                "description": "Kargo entegrasyonu erken 'teslim edildi' yazıyor.",
                "evidence_quotes": ["Teslim edildi yazıyor ama elimde yok"],
                "affected_surface": "mobil uygulama",
                "suggested_action": "Statü senkronizasyonunu webhook'a çevir",
                "share_estimate_pct": 62,
            }
        ],
    }


async def _bind_tenant(session: AsyncSession, tid: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tid)},
    )


async def _seed_reviews(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    category: str,
    perspective_code: str | None,
    count: int,
    sentiment: str = "NEGATIF",
    score: float = -0.8,
    review_date: datetime | None = None,
) -> None:
    """``count`` rows, all same (category, perspective, sentiment).
    ``review_date`` defaults to yesterday — comfortably inside every
    window this file exercises (rolling 90-day AND day-rounded
    90-day) regardless of what time of day the suite runs, so no test
    here is sensitive to a UTC-midnight edge."""
    when = review_date or (datetime.now(UTC) - timedelta(days=1))
    for i in range(count):
        body = f"{category} {sentiment} testi {uuid4().hex[:8]} {i}"
        session.add(
            Review(
                tenant_id=tenant_id,
                text=body,
                text_hash=review_text_hash(body),
                sentiment_label=sentiment,
                sentiment_score=score,
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


# ---------------------------------------------------------------------------
# Route layer — GET /root-cause/overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_empty_tenant_returns_no_cards(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["cards"] == []


@pytest.mark.asyncio
async def test_overview_orders_cards_picks_worst_perspective_and_parses_analysis(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """3 kategori, farklı negatif sayıları: kargo(20) > iade(8) >
    diğer(3-negatif+9-nötr). Doğrular: (a) kartlar negatif sayısına
    göre azalan sıralı, (b) kargo'da iki perspektif adayından daha
    kalabalık olanı ('order_status_wrong', 15 > 'late_delivery', 5)
    kazanır, (c) can_generate kovanın TÜM duygulardaki toplamına bakar
    — diğer'in 3 negatifi tek başına eşiği geçmez ama +9 nötr'le
    birlikte kova 12'ye çıkıp can_generate=True olur, iade'nin kovası
    yalnız 8 olduğu için (hepsi negatif) eşiğin altında kalır."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=15,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="late_delivery",
            count=5,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="iade",
            perspective_code="refund_delay",
            count=8,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="diğer",
            perspective_code="manual_error",
            count=3,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="diğer",
            perspective_code="manual_error",
            count=9,
            sentiment="NÖTR",
            score=0.0,
        )
        admin_session.add(
            RootCauseAnalysis(
                tenant_id=tid,
                primary_category_code="kargo",
                perspective_code="order_status_wrong",
                date_from=None,
                date_to=None,
                review_count=99,
                model_provider="gemini",
                model_name="gemini-3-flash-preview",
                payload=_payload(),
                generated_by_user_id=None,
            )
        )
        await admin_session.flush()

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, params={"limit": 3}, headers=_auth(token))
    assert r.status_code == 200, r.text
    cards = r.json()["cards"]

    assert [c["primary_category_code"] for c in cards] == ["kargo", "iade", "diğer"]

    kargo_card, iade_card, diger_card = cards
    assert kargo_card["negative_count"] == 20
    assert kargo_card["perspective_code"] == "order_status_wrong"
    assert kargo_card["can_generate"] is True
    assert kargo_card["share_pct"] == pytest.approx(64.5, abs=0.1)
    assert kargo_card["analysis"] is not None
    assert kargo_card["analysis"]["review_count"] == 99
    assert kargo_card["analysis"]["causes"][0]["affected_surface"] == "mobil uygulama"

    assert iade_card["negative_count"] == 8
    assert iade_card["perspective_code"] == "refund_delay"
    assert iade_card["can_generate"] is False
    assert iade_card["analysis"] is None

    assert diger_card["negative_count"] == 3
    assert diger_card["perspective_code"] == "manual_error"
    # Kova (12 = 3 negatif + 9 nötr) eşiği geçiyor, negatif sayısı tek
    # başına eşiğin altında kalsa bile.
    assert diger_card["can_generate"] is True
    assert diger_card["analysis"] is None


@pytest.mark.asyncio
async def test_overview_null_heavy_category_cannot_generate(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code=None,
            count=15,
        )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, headers=_auth(token))
    assert r.status_code == 200, r.text
    cards = r.json()["cards"]
    assert len(cards) == 1
    card = cards[0]
    assert card["primary_category_code"] == "kargo"
    assert card["perspective_code"] is None
    assert card["can_generate"] is False
    assert card["analysis"] is None


@pytest.mark.asyncio
async def test_overview_parses_malformed_payload_without_500(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """İki bozukluk türü, tek testte: (1) ``root_causes`` bir liste
    değil ('çöp') → boş causes ama summary korunur; (2) liste içinde
    dict-olmayan / zorunlu alanı eksik madde → o madde atlanır, geçerli
    madde kalır. İkisi de 200 döner, hiçbiri 500 atmaz."""
    user, tid, pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=12,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="iade",
            perspective_code="refund_delay",
            count=12,
        )
        admin_session.add(
            RootCauseAnalysis(
                tenant_id=tid,
                primary_category_code="kargo",
                perspective_code="order_status_wrong",
                date_from=None,
                date_to=None,
                review_count=12,
                model_provider="gemini",
                model_name="gemini-3-flash-preview",
                payload={"summary": "Kısmen bozuk payload", "root_causes": "çöp"},
                generated_by_user_id=None,
            )
        )
        admin_session.add(
            RootCauseAnalysis(
                tenant_id=tid,
                primary_category_code="iade",
                perspective_code="refund_delay",
                date_from=None,
                date_to=None,
                review_count=12,
                model_provider="gemini",
                model_name="gemini-3-flash-preview",
                payload={
                    "summary": "Kısmi geçerli liste",
                    "root_causes": [
                        {
                            "title": "Geçerli neden",
                            "description": "Açıklama metni",
                            "evidence_quotes": ["alıntı 1", 42],
                            "affected_surface": "web",
                            "suggested_action": "düzelt",
                            "share_estimate_pct": 40,
                        },
                        {"title": "Açıklaması eksik madde"},
                        "dict-olmayan-eleman",
                    ],
                },
                generated_by_user_id=None,
            )
        )
        await admin_session.flush()

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, headers=_auth(token))
    assert r.status_code == 200, r.text
    by_code = {c["primary_category_code"]: c for c in r.json()["cards"]}

    kargo_analysis = by_code["kargo"]["analysis"]
    assert kargo_analysis["summary"] == "Kısmen bozuk payload"
    assert kargo_analysis["causes"] == []

    iade_analysis = by_code["iade"]["analysis"]
    assert iade_analysis["summary"] == "Kısmi geçerli liste"
    assert len(iade_analysis["causes"]) == 1
    only_cause = iade_analysis["causes"][0]
    assert only_cause["title"] == "Geçerli neden"
    # Liste içindeki dict-olmayan eleman (42) sessizce atlandı.
    assert only_cause["evidence_quotes"] == ["alıntı 1"]


@pytest.mark.asyncio
async def test_overview_parses_headline_and_action_short(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Collapsed-card redesign fields (product-owner screenshot
    feedback): a cause carrying headline/action_short round-trips; a
    cause without them yields null for both (older persisted analyses
    predate the fields, frontend falls back to title/suggested_action);
    an over-long headline is trimmed to 60 chars defensively — the
    prompt caps it but a strict:false provider isn't bound by that."""
    user, tid, pw = semi_auto_tenant
    long_headline = "Ç" * 80  # > 60 karakter sınırı
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=12,
        )
        admin_session.add(
            RootCauseAnalysis(
                tenant_id=tid,
                primary_category_code="kargo",
                perspective_code="order_status_wrong",
                date_from=None,
                date_to=None,
                review_count=12,
                model_provider="gemini",
                model_name="gemini-3-flash-preview",
                payload={
                    "summary": "Kargo statüsü yanlış gösteriliyor.",
                    "root_causes": [
                        {
                            "title": "Uygulama statüyü yanlış gösteriyor",
                            "description": "Kargo entegrasyonu erken 'teslim edildi' yazıyor.",
                            "evidence_quotes": ["Teslim edildi yazıyor ama elimde yok"],
                            "affected_surface": "mobil uygulama",
                            "suggested_action": "Statü senkronizasyonunu webhook'a çevir",
                            "share_estimate_pct": 62,
                            "headline": long_headline,
                            "action_short": "Statü senkronizasyonunu webhook'a çevirin",
                        },
                        {
                            "title": "İkinci neden — vitrin alanları yok",
                            "description": "Eski analiz, headline/action_short'tan önce üretildi.",
                            "evidence_quotes": ["alıntı"],
                            "affected_surface": "web",
                            "suggested_action": "Eski önerinin aynısı",
                        },
                    ],
                },
                generated_by_user_id=None,
            )
        )
        await admin_session.flush()

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, headers=_auth(token))
    assert r.status_code == 200, r.text
    causes = r.json()["cards"][0]["analysis"]["causes"]

    with_fields, without_fields = causes
    # Kelime sınırı yok (tek uzun kelime) -> 60 karakter + "…"
    assert with_fields["headline"] == long_headline[:60] + "…"
    assert with_fields["action_short"] == "Statü senkronizasyonunu webhook'a çevirin"

    # Eski analiz: vitrin alanları title / suggested_action'dan türetilir
    assert without_fields["headline"] == "İkinci neden — vitrin alanları yok"
    assert without_fields["action_short"] == "Eski önerinin aynısı"


# ---------------------------------------------------------------------------
# "generating" flag — set by batch_analyzer._enqueue_root_cause_auto_gen
# at enqueue time, cleared by generate_root_causes_task's finally block.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_generating_false_when_no_flag_set(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    fake_redis_client: Any,
) -> None:
    del fake_redis_client  # installed only so the read hits a real (empty) client
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["generating"] is False


@pytest.mark.asyncio
async def test_overview_generating_true_when_flag_set(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    fake_redis_client: Any,
) -> None:
    user, tid, pw = semi_auto_tenant
    await fake_redis_client.set(f"root_cause_autogen:{tid}", "1", ex=1200)

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(_OVERVIEW_ENDPOINT, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["generating"] is True


# ---------------------------------------------------------------------------
# day_rounded_window + post-batch auto-generation task
# ---------------------------------------------------------------------------


def test_day_rounded_window_dedups_within_same_utc_day() -> None:
    from imga_api.services.root_cause_service import day_rounded_window

    morning = day_rounded_window(datetime(2026, 8, 31, 3, 0, tzinfo=UTC))
    evening = day_rounded_window(datetime(2026, 8, 31, 23, 59, tzinfo=UTC))
    assert morning == evening

    date_from, date_to = morning
    assert date_to == date(2026, 8, 31)
    assert date_to - date_from == timedelta(days=90)

    next_day = day_rounded_window(datetime(2026, 9, 1, 0, 0, 1, tzinfo=UTC))
    assert next_day != morning


@pytest.mark.asyncio
async def test_auto_gen_task_picks_top_categories_and_dedups_same_day(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``RootCauseService.generate`` mocklanır — hiç gerçek LLM çağrısı
    yok. Doğrular: en fazla 3 kez çağrılır, her seferinde
    ``force_refresh=False``, ve aynı gün içindeki ikinci koşu AYNI
    (kategori, perspektif, date_from, date_to) dörtlüsünü üretir (12s
    cache'in gerçekten dedup edebilmesi için kritik sözleşme)."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        # Toplam 60 yorum — _AUTO_GEN_MIN_TENANT_REVIEWS (50) eşiğini
        # geçiyor; iki kategori, ikisi de kova eşiğini (10) aşıyor.
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=40,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="iade",
            perspective_code="refund_delay",
            count=20,
        )

    from imga_api.services import root_cause_service
    from imga_api.workers import arq_worker, batch_analyzer

    mock_generate = AsyncMock(return_value={"id": str(uuid4())})
    monkeypatch.setattr(root_cause_service.RootCauseService, "generate", mock_generate)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    try:
        await arq_worker.generate_root_causes_task({"worker_context": context}, str(tid))
        assert mock_generate.await_count == 2
        assert mock_generate.await_count <= 3
        for call in mock_generate.await_args_list:
            assert call.kwargs["force_refresh"] is False

        first_run = {
            (
                call.kwargs["primary_category"],
                call.kwargs["perspective_code"],
                call.kwargs["date_from"],
                call.kwargs["date_to"],
            )
            for call in mock_generate.await_args_list
        }
        mock_generate.reset_mock()

        await arq_worker.generate_root_causes_task({"worker_context": context}, str(tid))
        second_run = {
            (
                call.kwargs["primary_category"],
                call.kwargs["perspective_code"],
                call.kwargs["date_from"],
                call.kwargs["date_to"],
            )
            for call in mock_generate.await_args_list
        }
        assert first_run == second_run
    finally:
        await context.dispose()


@pytest.mark.asyncio
async def test_auto_gen_task_skips_tenant_below_review_floor(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """49 yorum (_AUTO_GEN_MIN_TENANT_REVIEWS - 1) → hiç generate
    çağrılmaz, kova sorgusu bile koşmaz."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=49,
        )

    from imga_api.services import root_cause_service
    from imga_api.workers import arq_worker, batch_analyzer

    mock_generate = AsyncMock()
    monkeypatch.setattr(root_cause_service.RootCauseService, "generate", mock_generate)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    try:
        await arq_worker.generate_root_causes_task({"worker_context": context}, str(tid))
        mock_generate.assert_not_awaited()
    finally:
        await context.dispose()


@pytest.mark.asyncio
async def test_auto_gen_task_force_refresh_follows_rows_succeeded_threshold(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis_client: Any,
) -> None:
    """2026-09 maliyet kuralı: ``force_refresh`` yalnızca tetikleyen
    batch'in ``rows_succeeded``'ı ``_AUTO_GEN_FORCE_REFRESH_MIN_ROWS``
    (200) ve üzerindeyse True geçilir; altında (199) hep False kalır."""
    del fake_redis_client  # finally'deki flag-clear çağrısını gerçek ağdan uzak tutar
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="kargo",
            perspective_code="order_status_wrong",
            count=40,
        )
        await _seed_reviews(
            admin_session,
            tenant_id=tid,
            category="iade",
            perspective_code="refund_delay",
            count=20,
        )

    from imga_api.services import root_cause_service
    from imga_api.workers import arq_worker, batch_analyzer

    mock_generate = AsyncMock(return_value={"id": str(uuid4())})
    monkeypatch.setattr(root_cause_service.RootCauseService, "generate", mock_generate)

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    try:
        await arq_worker.generate_root_causes_task(
            {"worker_context": context}, str(tid), rows_succeeded=199
        )
        assert mock_generate.await_count >= 1
        for call in mock_generate.await_args_list:
            assert call.kwargs["force_refresh"] is False
        mock_generate.reset_mock()

        await arq_worker.generate_root_causes_task(
            {"worker_context": context}, str(tid), rows_succeeded=200
        )
        assert mock_generate.await_count >= 1
        for call in mock_generate.await_args_list:
            assert call.kwargs["force_refresh"] is True
    finally:
        await context.dispose()


@pytest.mark.asyncio
async def test_enqueue_root_cause_auto_gen_job_id_differs_per_batch(
    batch_client: TestClient,
    fake_redis_client: Any,
) -> None:
    """``batch_analyzer._enqueue_root_cause_auto_gen``: aynı tenant için
    iki farklı ``batch_job_id`` FARKLI arq ``_job_id`` üretmeli — eski
    tenant+gün formatı aynı gün içindeki ikinci yüklemeyi arq'ın kendi
    job-id dedup'ına düşürüyordu (bkz. fonksiyon docstring'i)."""
    del fake_redis_client  # flag-set çağrısını gerçek ağdan uzak tutar
    from imga_api.workers import batch_analyzer

    test_app = batch_client.app  # type: ignore[attr-defined]
    context = await batch_analyzer.build_worker_context(
        pipeline=test_app.state.pipeline,
        tenant_config_cache=test_app.state.tenant_config_cache,
        settings=test_app.state.settings.batch,
    )
    context.arq_pool = AsyncMock()
    tid = uuid4()
    batch_a = uuid4()
    batch_b = uuid4()
    try:
        await batch_analyzer._enqueue_root_cause_auto_gen(
            tid, context, batch_job_id=batch_a, rows_succeeded=5
        )
        await batch_analyzer._enqueue_root_cause_auto_gen(
            tid, context, batch_job_id=batch_b, rows_succeeded=5
        )
        job_ids = [call.kwargs["_job_id"] for call in context.arq_pool.enqueue_job.await_args_list]
        assert len(job_ids) == 2
        assert job_ids[0] != job_ids[1]
        assert str(batch_a) in job_ids[0]
        assert str(batch_b) in job_ids[1]
    finally:
        await context.dispose()


def test_validate_and_normalise_keeps_and_trims_showcase_fields() -> None:
    """2026-09-01 — kapalı kart alanları (headline/action_short) persist
    yolunda düşürülmemeli; str değilse None, uzunsa kırpılır."""
    from imga_api.services.root_cause_service import _validate_and_normalise

    payload = {
        "summary": "özet",
        "root_causes": [
            {
                "title": "uzun başlık",
                "description": "açıklama",
                "evidence_quotes": ["a"],
                "affected_surface": "x",
                "suggested_action": "uzun aksiyon",
                "share_estimate_pct": 10,
                "headline": " " + "H" * 70 + " ",
                "action_short": "Evrak isteğini aynı gün SMS ile bildirin.",
            },
            {
                "title": "Eski bir kök neden başlığı",
                "description": "Yeni alanlardan önce üretilmiş madde.",
                "headline": 42,
            },
        ],
    }
    out = _validate_and_normalise(payload)
    first, second = out["root_causes"]
    assert first["headline"] == "H" * 60 + "…"
    assert first["action_short"] == "Evrak isteğini aynı gün SMS ile bildirin."
    # headline sayı -> title'dan türetilir; suggested_action yok -> action None
    assert second["headline"] == "Eski bir kök neden başlığı"
    assert second["action_short"] is None


def test_validate_and_normalise_rejects_placeholder_skeleton() -> None:
    """2026-09-01 — GLM ara sıra muhakemesiz "..." iskeleti döndürüyor;
    böyle bir yanıt RootCausePlaceholderError ile reddedilmeli (generate
    yeniden dener), asla kaydedilmemeli."""
    from imga_api.services.root_cause_service import (
        RootCausePlaceholderError,
        _validate_and_normalise,
    )

    skeleton = {
        "summary": "...",
        "root_causes": [
            {
                "title": "...",
                "description": "...",
                "evidence_quotes": ["...", "..."],
                "affected_surface": "...",
                "suggested_action": "...",
                "share_estimate_pct": 40,
                "headline": "...",
                "action_short": "...",
            }
        ],
    }
    with pytest.raises(RootCausePlaceholderError):
        _validate_and_normalise(skeleton)

    # Karışık yanıt: bir gerçek + bir iskelet madde → gerçek olan kalır,
    # özet yer tutucuysa boşa çevrilir.
    mixed = {
        "summary": "…",
        "root_causes": [
            skeleton["root_causes"][0],
            {"title": "Gerçek bir kök neden başlığı", "description": "Yeterince uzun açıklama."},
        ],
    }
    out = _validate_and_normalise(mixed)
    assert len(out["root_causes"]) == 1
    assert out["summary"] == ""


def test_showcase_helpers_word_boundary_and_first_sentence() -> None:
    from imga_api.services.root_cause_service import showcase_action, showcase_headline

    long_title = "Gümrük ek belge talebi bildirimlerinin göndericiye zamanında ulaşmaması sorunu"
    h = showcase_headline(None, long_title)
    assert h is not None and h.endswith("…") and len(h) <= 61 and " " in h
    assert not h[:-1].endswith(" ")
    assert showcase_headline("...", long_title) == h  # yer tutucu -> title'a düşer
    action = (
        "Gümrük ek belge talebi gelen gönderilerde müşteriye aynı gün SMS gönderin. "
        "Çağrı merkezi scriptine hazır cevap ekleyin."
    )
    assert showcase_action(None, action) == (
        "Gümrük ek belge talebi gelen gönderilerde müşteriye aynı gün SMS gönderin."
    )
    assert showcase_action("Evrak isteğini aynı gün SMS ile bildirin", action) == (
        "Evrak isteğini aynı gün SMS ile bildirin"
    )
    assert showcase_action(None, None) is None
