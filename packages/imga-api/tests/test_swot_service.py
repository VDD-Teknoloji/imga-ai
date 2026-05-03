"""Sprint 8.3.6 / Alt-Faz 8.3.6.3 — SwotService orchestrator tests.

Layered coverage:

  * Pure prompt-render unit tests (no DB, no LLM, no Redis) — exercise
    the Jinja branches we hand-wrote in swot_v1.py.
  * Pure response-validation unit tests — defence-in-depth schema check.
  * DB + provider-mock + fakeredis integration tests — the full
    generate() flow. fakeredis injected via set_redis_client; provider
    via the SwotService constructor's ``provider`` kwarg.

Transaction discipline: every integration test runs the bind_tenant +
service.generate + DB verify inside ONE ``async with admin_session.
begin()`` block. SwotService flushes (autobegin) but does not commit;
keeping the verify inside the same transaction avoids the
"transaction already begun" surprise the conftest's ``cleanup_tenant``
runs into otherwise.

The mock_gemini_credential + encryption_helper + tenant_with_context
fixtures from conftest.py do the encrypted-credential setup. No real
Gemini SDK call ever fires — the provider mock supplies the dict the
service expects.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from imga_core.llm.errors import (
    AllKeysExhaustedError,
    InvalidKeyError,
)
from imga_db.models import StrategicReport, TenantLlmCredential, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.cache.redis_client import set_redis_client
from imga_api.llm.prompts.swot_v1 import (
    SWOT_RESPONSE_SCHEMA,
    render_swot_user_prompt,
)
from imga_api.services.swot_service import (
    NoCredentialsError,
    SwotResponseInvalidError,
    SwotService,
)

# ---------------------------------------------------------------------------
# Pure prompt-render units (no DB)
# ---------------------------------------------------------------------------


def _baseline_render_context(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "industry_label": "E-ticaret",
        "industry_other_text": None,
        "company_size_label": "Orta (11-50)",
        "business_description": "Test açıklaması",
        "date_from": None,
        "date_to": None,
        "total_reviews": 1000,
        "crisis_count": 50,
        "sensitive_topics_count": 80,
        "avg_sentiment_score": -0.32,
        "sentiment_distribution": {
            "negative": 600, "neutral": 200, "positive": 200
        },
        "nps_score": -15.5,
        "nps_coverage_percent": 42.0,
        "nps_distribution": {
            "detractor": 500, "passive": 250, "promoter": 250
        },
        "category_distribution": [
            {"code": "kargo", "label_tr": "Kargo", "count": 300, "pct": 30.0},
        ],
        "company_perspective_distribution": [
            {"code": "shipment_not_arrived", "label_tr": "Kargom ulaşmadı",
             "count": 250, "pct": 25.0},
        ],
        "unmatched_perspective_count": 300,
    }
    base.update(overrides)
    return base


def test_user_prompt_renders_with_industry_other_text() -> None:
    """``industry_other_text`` non-empty appears parenthetically next
    to the resolved label — the renderer doesn't drop it."""
    rendered = render_swot_user_prompt(
        _baseline_render_context(
            industry_label="Diğer",
            industry_other_text="Kuyumculuk",
        )
    )
    assert "Sektör: Diğer (Kuyumculuk)" in rendered


def test_user_prompt_renders_without_nps_when_no_data() -> None:
    """``nps_score=None`` triggers the "veri yetersiz" branch instead
    of leaking ``None`` into the prompt text."""
    rendered = render_swot_user_prompt(
        _baseline_render_context(nps_score=None)
    )
    assert "NPS verisi henüz yetersiz" in rendered
    assert "None" not in rendered  # No raw Python literals leaking through.


def test_user_prompt_renders_with_date_window() -> None:
    """ISO date strings appear in the analysis-period block when both
    bounds are set."""
    rendered = render_swot_user_prompt(
        _baseline_render_context(
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
        )
    )
    assert "2026-01-01 – 2026-03-31" in rendered


def test_user_prompt_renders_all_time_when_dates_missing() -> None:
    rendered = render_swot_user_prompt(
        _baseline_render_context(date_from=None, date_to=None)
    )
    assert "Tüm zaman" in rendered


def test_user_prompt_skips_unmatched_line_when_zero() -> None:
    """The "Eşleşmeyen: N yorum" line should NOT appear when
    ``unmatched_perspective_count == 0`` — keep the prompt tight."""
    rendered = render_swot_user_prompt(
        _baseline_render_context(unmatched_perspective_count=0)
    )
    assert "Eşleşmeyen" not in rendered


def test_response_validation_rejects_missing_required_fields() -> None:
    """SwotService validates the LLM payload against the top-level
    required fields (defence-in-depth — Gemini SDK enforces too)."""
    bad = {"strengths": [], "weaknesses": [], "opportunities": []}
    # Missing threats + strategic_recommendations.
    with pytest.raises(SwotResponseInvalidError, match="missing required fields"):
        SwotService._validate_swot_response(bad)


def test_response_validation_accepts_complete_payload() -> None:
    good = {k: [] for k in SWOT_RESPONSE_SCHEMA["required"]}
    # Should not raise.
    SwotService._validate_swot_response(good)


# ---------------------------------------------------------------------------
# DB + provider-mock + fakeredis integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_redis_client() -> Any:
    """In-process Redis double. Installed as the module singleton via
    set_redis_client; reset to None after the test so the next one
    gets a fresh instance (or the production lazy path)."""
    import fakeredis.aioredis as fakeredis_async

    fake = fakeredis_async.FakeRedis(decode_responses=False)
    set_redis_client(fake)
    yield fake
    set_redis_client(None)


def _swot_payload() -> dict[str, Any]:
    """Minimal valid SWOT payload — every required field present, no
    semantic check beyond shape."""
    item = {"title": "X", "description": "Y", "evidence": "Z"}
    rec = {
        "title": "A", "description": "B",
        "priority": "yüksek", "estimated_impact": "orta",
    }
    return {
        "strengths": [item, item],
        "weaknesses": [item, item],
        "opportunities": [item, item],
        "threats": [item, item],
        "strategic_recommendations": [rec, rec, rec],
    }


def _build_mock_provider(
    *,
    payload: dict[str, Any] | None = None,
    side_effect: Exception | None = None,
) -> Any:
    """Mock GeminiProvider for SwotService injection. ``generate_swot``
    is the only attribute the service touches."""
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    if side_effect is not None:
        provider.generate_swot = AsyncMock(side_effect=side_effect)  # type: ignore[method-assign]
    else:
        provider.generate_swot = AsyncMock(  # type: ignore[method-assign]
            return_value=payload or _swot_payload()
        )
    return provider


async def _bind_tenant(session: AsyncSession, tid: UUID) -> None:
    """Set app.current_tenant_id on the live session. Caller owns the
    transaction. Used inside ``async with session.begin()`` blocks
    because the encryption_helper-driven mock_gemini_credential
    factory and SwotService both run in the same outer transaction."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tid)},
    )


@pytest.mark.asyncio
async def test_swot_service_no_credentials_raises(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    fake_redis_client: Any,
) -> None:
    """Tenant has no rows in tenant_llm_credentials → service raises
    NoCredentialsError before any LLM call."""
    del fake_redis_client
    _user, tid, _pw = tenant_with_context
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = SwotService(
            admin_session,
            tid,
            user_id=None,
            provider=_build_mock_provider(),
        )
        with pytest.raises(NoCredentialsError):
            await service.generate()


@pytest.mark.asyncio
async def test_swot_service_generate_cache_miss(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """First call: cache miss → LLM call fires → result cached. The
    persisted strategic_reports row carries input_stats + output_payload
    + generation_duration_ms."""
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    payload = _swot_payload()
    provider = _build_mock_provider(payload=payload)
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = SwotService(
            admin_session, tid, user_id=None, provider=provider
        )
        result = await service.generate()

    # Provider was called exactly once, with the rotator's per-call key.
    provider.generate_swot.assert_awaited_once()
    call_kwargs = provider.generate_swot.await_args.kwargs
    assert call_kwargs["api_key"] == "fake-key"

    # Result shape — service serialises the row to a dict.
    assert result["report_type"] == "swot"
    assert result["output_payload"] == payload
    assert result["generation_duration_ms"] is not None
    assert result["generation_duration_ms"] >= 0

    # Cache populated.
    cache_keys = await fake_redis_client.keys("swot:*")
    assert len(cache_keys) == 1


@pytest.mark.asyncio
async def test_swot_service_generate_cache_hit_skips_llm(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """Second call with identical filters → cache hit → provider NOT
    called the second time."""
    del fake_redis_client
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = SwotService(
            admin_session, tid, user_id=None, provider=provider
        )
        first = await service.generate()
        assert provider.generate_swot.await_count == 1

        second = await service.generate()

    # Provider NOT called the second time.
    assert provider.generate_swot.await_count == 1
    # Same payload returned from cache.
    assert second["output_payload"] == first["output_payload"]


@pytest.mark.asyncio
async def test_swot_service_force_refresh_bypasses_cache(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """force_refresh=True → cache lookup skipped → provider called
    even when a hit exists."""
    del fake_redis_client
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = SwotService(
            admin_session, tid, user_id=None, provider=provider
        )
        await service.generate()
        assert provider.generate_swot.await_count == 1

        # force_refresh: provider called again despite cache hit.
        await service.generate(force_refresh=True)
    assert provider.generate_swot.await_count == 2


@pytest.mark.asyncio
async def test_swot_service_persists_report_to_db(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """Successful generation writes one strategic_reports row with
    the expected report_type, model_name, and structurally-correct
    input_stats / output_payload. Generation + verify share one
    transaction so the autobegin from service.flush doesn't conflict
    with the verify-block's own begin."""
    del fake_redis_client
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    payload = _swot_payload()
    provider = _build_mock_provider(payload=payload)
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = SwotService(
            admin_session, tid, user_id=None, provider=provider
        )
        result = await service.generate()

        # Verify persistence inside the same transaction so the row
        # the service flushed is visible without committing.
        row = (
            await admin_session.execute(
                select(StrategicReport).where(
                    StrategicReport.id == UUID(result["id"])
                )
            )
        ).scalar_one()
        assert row.report_type == "swot"
        assert row.model_name == "gemini-2.5-pro"
        assert row.output_payload == payload
        # input_stats has the snapshot fields we documented.
        assert "stats_hash" in row.input_stats
        assert "total_reviews" in row.input_stats


@pytest.mark.asyncio
async def test_swot_service_all_keys_exhausted_marks_invalid_keys(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    fake_redis_client: Any,
) -> None:
    """Two keys, both InvalidKey → AllKeysExhausted re-raises AND
    last_failed_at is stamped on both rows so the UI can surface
    'needs attention'."""
    del fake_redis_client
    _user, tid, _pw = tenant_with_context
    cred1_id = await mock_gemini_credential(tid, "bad-1", priority=0)
    cred2_id = await mock_gemini_credential(tid, "bad-2", priority=1)

    provider = _build_mock_provider(side_effect=InvalidKeyError("revoked"))
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = SwotService(
            admin_session, tid, user_id=None, provider=provider
        )
        with pytest.raises(AllKeysExhaustedError):
            await service.generate()

        # Verify last_failed_at inside the same transaction.
        rows = (
            await admin_session.execute(
                select(TenantLlmCredential).where(
                    TenantLlmCredential.id.in_([cred1_id, cred2_id])
                )
            )
        ).scalars().all()
        assert all(r.last_failed_at is not None for r in rows)


@pytest.mark.asyncio
async def test_swot_service_continues_when_redis_down(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """Redis client raises on every op → service still completes the
    LLM path and returns a result. The cache is best-effort by design;
    a Redis blip mustn't break SWOT generation."""
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    # Inject a "broken" client that raises on get/set.
    broken = AsyncMock()
    broken.get = AsyncMock(side_effect=ConnectionError("redis down"))
    broken.set = AsyncMock(side_effect=ConnectionError("redis down"))
    set_redis_client(broken)
    try:
        provider = _build_mock_provider()
        async with admin_session.begin():
            await _bind_tenant(admin_session, tid)
            service = SwotService(
                admin_session, tid, user_id=None, provider=provider
            )
            result = await service.generate()
            assert result["report_type"] == "swot"
            # Provider was called (no cache short-circuit).
            provider.generate_swot.assert_awaited_once()
    finally:
        set_redis_client(None)
