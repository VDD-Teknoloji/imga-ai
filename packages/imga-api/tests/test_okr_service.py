"""Sprint 8.3.6 / Alt-Faz 8.3.6.4 — OkrService tests.

OKR is a thinner orchestrator than SWOT (no cache, no stats
aggregator) but the source-report integrity guards earn their own
test surface: missing UUID, wrong report_type, cross-tenant access
all collapse to the same SourceReportNotFoundError.

Same fixture rules as SWOT tests:
  * tenant_with_context for industry/size/desc
  * mock_gemini_credential for encrypted-credential setup
  * Provider injected via OkrService constructor's ``provider`` kwarg
  * Whole DB flow inside one ``async with admin_session.begin()``
    block to avoid the "transaction already begun" autobegin trap
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from imga_core.llm.errors import (
    AllKeysExhaustedError,
    InvalidKeyError,
)
from imga_db.models import StrategicReport, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.llm.prompts.okr_v1 import (
    OKR_RESPONSE_SCHEMA,
    render_okr_user_prompt,
)
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.okr_service import (
    OkrResponseInvalidError,
    OkrService,
    SourceReportNotFoundError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _swot_payload() -> dict[str, Any]:
    """Minimal SWOT payload to anchor the OKR generation."""
    item = {
        "title": "Hızlı kargo",
        "description": "Müşteriler kargo süresinden memnun.",
        "evidence": "%30 pozitif yorum",
    }
    rec = {
        "title": "Kargo SLA'sı",
        "description": "Mevcut başarıyı pekiştir.",
        "priority": "yüksek",
        "estimated_impact": "yüksek",
    }
    return {
        "strengths": [item, item],
        "weaknesses": [item, item],
        "opportunities": [item, item],
        "threats": [item, item],
        "strategic_recommendations": [rec, rec, rec],
    }


def _swot_input_stats() -> dict[str, Any]:
    """Minimal input_stats — OKR only reads industry / company_size /
    industry_other_text from here."""
    return {
        "industry": "e_commerce",
        "industry_other_text": None,
        "company_size": "medium",
        "business_description": "Test",
        "total_reviews": 1000,
        "stats_hash": "abc",
    }


def _okr_payload() -> dict[str, Any]:
    """Minimal valid OKR payload — every required field present."""
    kr = {
        "text": "12 hafta içinde NPS skorunu +10 puan artır.",
        "metric": "NPS skoru",
        "baseline": "-15",
        "target": "-5",
    }
    return {
        "objectives": [
            {
                "objective": "Müşteri memnuniyetini ölçülebilir biçimde artır.",
                "rationale": "Zayıf yön: kargo gecikmesi.",
                "key_results": [kr, kr],
            },
            {
                "objective": "Kargo SLA'sını pekiştir.",
                "rationale": "Güçlü yön: hızlı kargo.",
                "key_results": [kr, kr],
            },
        ],
    }


async def _bind_tenant(session: AsyncSession, tid: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tid)},
    )


def _build_mock_provider(
    *,
    payload: dict[str, Any] | None = None,
    side_effect: Exception | None = None,
    token_usage: dict[str, int] | None = None,
) -> Any:
    """Mock GeminiProvider with generate_okr stubbed out. SwotService
    tests share the same ``__new__`` trick so the SDK never imports.

    Sprint 8.3.6.5 — provider returns ``(payload, token_usage)``."""
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    if side_effect is not None:
        provider.generate_okr = AsyncMock(side_effect=side_effect)  # type: ignore[method-assign]
    else:
        provider.generate_okr = AsyncMock(  # type: ignore[method-assign]
            return_value=(payload or _okr_payload(), token_usage)
        )
    return provider


async def _seed_swot(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    payload: dict[str, Any] | None = None,
    input_stats: dict[str, Any] | None = None,
    report_type: str = "swot",
) -> UUID:
    """Insert a strategic_reports row directly. Used as the source-
    report parent for OKR tests; ``report_type`` is parameterised so
    a single helper covers both happy-path SWOT and the wrong-type
    rejection test."""
    row = StrategicReport(
        tenant_id=tenant_id,
        report_type=report_type,
        input_stats=input_stats or _swot_input_stats(),
        output_payload=payload or _swot_payload(),
        model_name="gemini-2.5-pro",
    )
    session.add(row)
    await session.flush()
    return row.id


# ---------------------------------------------------------------------------
# Pure prompt-render unit tests
# ---------------------------------------------------------------------------


def test_okr_user_prompt_includes_all_swot_sections() -> None:
    """The four SWOT arrays + recommendations all need to surface in
    the OKR user prompt; otherwise the model has no anchor for its
    Objectives."""
    rendered = render_okr_user_prompt(
        {
            "strengths": [{"title": "S1", "description": "Sd", "evidence": "Se"}],
            "weaknesses": [{"title": "W1", "description": "Wd", "evidence": "We"}],
            "opportunities": [{"title": "O1", "description": "Od", "evidence": "Oe"}],
            "threats": [{"title": "T1", "description": "Td", "evidence": "Te"}],
            "strategic_recommendations": [
                {
                    "title": "R1",
                    "description": "Rd",
                    "priority": "yüksek",
                    "estimated_impact": "orta",
                }
            ],
            "industry_label": "E-ticaret",
            "company_size_label": "Orta (11-50)",
        }
    )
    assert "S1" in rendered
    assert "W1" in rendered
    assert "O1" in rendered
    assert "T1" in rendered
    assert "R1" in rendered
    assert "yüksek öncelik" in rendered
    assert "Sektör: E-ticaret" in rendered
    assert "Büyüklük: Orta (11-50)" in rendered


def test_okr_response_validation_rejects_missing_objectives() -> None:
    """Defence-in-depth: an empty payload (no objectives key) must
    fail before reaching the DB."""
    with pytest.raises(OkrResponseInvalidError, match="missing required fields"):
        OkrService._validate_okr_response({})


def test_okr_response_validation_accepts_complete_payload() -> None:
    OkrService._validate_okr_response({"objectives": []})


def test_okr_schema_does_not_use_minitems() -> None:
    """Schema regression guard. Same Gemini SDK proto-Schema crash as
    SWOT — ``minItems`` / ``maxItems`` raise ``ValueError: Unknown
    field for Schema: minItems`` at validation time. The 2-4 / 2-4
    OKR spec lives in OKR_SYSTEM_PROMPT + a permissive service-side
    guard instead."""
    schema_str = json.dumps(OKR_RESPONSE_SCHEMA)
    assert "minItems" not in schema_str
    assert "maxItems" not in schema_str


# ---------------------------------------------------------------------------
# DB + provider-mock integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_okr_generate_from_valid_swot_persists_report(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """Happy path: SWOT exists → OKR generated → strategic_reports
    row written with source_report_id linking back."""
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    payload = _okr_payload()
    provider = _build_mock_provider(payload=payload)
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        swot_id = await _seed_swot(admin_session, tid)

        service = OkrService(
            admin_session, tid, user_id=None, provider=provider
        )
        result = await service.generate(swot_id)

        # Result shape — service serialises the row.
        assert result["report_type"] == "okr"
        assert result["output_payload"] == payload
        assert result["source_report_id"] == str(swot_id)
        assert result["generation_duration_ms"] is not None

        # Provider called exactly once with the rotator's per-call key.
        provider.generate_okr.assert_awaited_once()
        call_kwargs = provider.generate_okr.await_args.kwargs
        assert call_kwargs["api_key"] == "fake-key"


@pytest.mark.asyncio
async def test_okr_generate_persists_with_correct_source_link(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """Round-trip via the DB: the persisted strategic_reports row
    carries source_report_id pointing at the parent SWOT."""
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        swot_id = await _seed_swot(admin_session, tid)

        service = OkrService(
            admin_session, tid, user_id=None, provider=provider
        )
        result = await service.generate(swot_id)

        row = (
            await admin_session.execute(
                select(StrategicReport).where(
                    StrategicReport.id == UUID(result["id"])
                )
            )
        ).scalar_one()
        assert row.report_type == "okr"
        assert row.source_report_id == swot_id
        # Date window inherited from the parent SWOT.
        assert row.date_from is None
        assert row.date_to is None


@pytest.mark.asyncio
async def test_okr_generate_source_report_missing_raises(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """Random UUID that doesn't resolve to any row → 404-equivalent."""
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    bogus_id = uuid4()
    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        service = OkrService(
            admin_session, tid, user_id=None, provider=provider
        )
        with pytest.raises(SourceReportNotFoundError):
            await service.generate(bogus_id)
        # Provider never invoked.
        provider.generate_okr.assert_not_awaited()


@pytest.mark.asyncio
async def test_okr_generate_source_wrong_type_raises(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """Passing an OKR row's id (not a SWOT) is a bug — the generator
    must reject it. Same exception class as missing-UUID; the route
    returns 404 either way."""
    _user, tid, _pw = tenant_with_context
    await mock_gemini_credential(tid, "fake-key", priority=0)

    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        # Seed a row of report_type='okr' (not swot).
        not_a_swot_id = await _seed_swot(
            admin_session, tid, report_type="okr"
        )
        service = OkrService(
            admin_session, tid, user_id=None, provider=provider
        )
        with pytest.raises(SourceReportNotFoundError):
            await service.generate(not_a_swot_id)


@pytest.mark.asyncio
async def test_okr_generate_source_other_tenant_raises(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """RLS keeps cross-tenant SWOT rows hidden; the explicit
    tenant_id = self check is the belt-and-braces. A SWOT seeded
    under one tenant must not be reachable by another tenant's
    OkrService instance."""
    user_a, tid_a, _pw_a = tenant_with_context
    await mock_gemini_credential(tid_a, "fake-key-a", priority=0)

    # Seed a SWOT under tenant A.
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid_a)
        swot_id = await _seed_swot(admin_session, tid_a)

    # Now create a second tenant via the seed helper used elsewhere.
    from tests.batch_helpers import cleanup_tenant, seed_tenant_with_admin

    user_b, tid_b, _pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="OKR Other"
    )
    try:
        provider = _build_mock_provider()
        async with admin_session.begin():
            await _bind_tenant(admin_session, tid_b)
            service = OkrService(
                admin_session, tid_b, user_id=None, provider=provider
            )
            with pytest.raises(SourceReportNotFoundError):
                # B asks for A's swot_id → not found.
                await service.generate(swot_id)
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)
    del user_a  # silences ARG inference; user_a is not consumed.


@pytest.mark.asyncio
async def test_okr_generate_no_credentials_raises(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
) -> None:
    """Tenant with a SWOT but no LLM keys → NoCredentialsError. The
    service short-circuits before any LLM call."""
    _user, tid, _pw = tenant_with_context
    provider = _build_mock_provider()
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        swot_id = await _seed_swot(admin_session, tid)
        service = OkrService(
            admin_session, tid, user_id=None, provider=provider
        )
        with pytest.raises(NoCredentialsError):
            await service.generate(swot_id)
    provider.generate_okr.assert_not_awaited()


@pytest.mark.asyncio
async def test_okr_generate_all_keys_exhausted_marks_invalid_keys(
    admin_session: AsyncSession,
    tenant_with_context: tuple[User, UUID, str],
    mock_gemini_credential: Any,
) -> None:
    """Two keys, both InvalidKey → AllKeysExhausted; both rows get
    last_failed_at stamped (same convention SwotService uses)."""
    _user, tid, _pw = tenant_with_context
    cred1_id = await mock_gemini_credential(tid, "bad-1", priority=0)
    cred2_id = await mock_gemini_credential(tid, "bad-2", priority=1)

    provider = _build_mock_provider(side_effect=InvalidKeyError("revoked"))
    async with admin_session.begin():
        await _bind_tenant(admin_session, tid)
        swot_id = await _seed_swot(admin_session, tid)
        service = OkrService(
            admin_session, tid, user_id=None, provider=provider
        )
        with pytest.raises(AllKeysExhaustedError):
            await service.generate(swot_id)

        from imga_db.models import TenantLlmCredential

        rows = (
            await admin_session.execute(
                select(TenantLlmCredential).where(
                    TenantLlmCredential.id.in_([cred1_id, cred2_id])
                )
            )
        ).scalars().all()
        assert all(r.last_failed_at is not None for r in rows)


# Placeholder used to verify the schema export survives an import
# regression — costs nothing, catches a future ``__all__`` typo.
def test_okr_schema_top_level_required_is_objectives() -> None:
    assert OKR_RESPONSE_SCHEMA["required"] == ["objectives"]
