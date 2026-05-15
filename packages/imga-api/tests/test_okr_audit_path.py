"""Sprint 9.5.6 — OKR service audit row regression.

Sibling to test_swot_audit_path.py — same gap (no LLMCallAuditor
wrap pre-9.5.6), same fix. Differences from SWOT:

  * call_type is 'okr' (not 'strategic_report').
  * OKR generation REQUIRES a parent SWOT row, so the test seeds
    one before kicking off OKR.
  * related_entity_id should carry the parent SWOT's id.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from imga_core.llm.errors import AllKeysExhaustedError
from imga_core.llm.key_rotation import GeminiKey
from imga_db.models import LlmCallAudit, StrategicReport, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.okr_service import OkrService


async def _seed_swot(
    admin_session: AsyncSession, tenant_id: UUID
) -> UUID:
    """Minimal SWOT row so OkrService._load_source_swot finds a
    parent. The output_payload shape mirrors the SWOT schema enough
    for ``_render_context`` to walk without crashing."""
    payload: dict[str, Any] = {
        "strengths": [
            {"title": "S1", "description": "d", "evidence": "e"},
        ],
        "weaknesses": [],
        "opportunities": [],
        "threats": [],
        "strategic_recommendations": [
            {
                "title": "rec",
                "description": "d",
                "priority": "high",
                "estimated_impact": "high",
            },
        ],
    }
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        row = StrategicReport(
            tenant_id=tenant_id,
            report_type="swot",
            input_stats={"total_reviews": 0},
            model_name="test",
            output_payload=payload,
        )
        admin_session.add(row)
        await admin_session.flush()
        rid = row.id
    return rid


@pytest.mark.asyncio
async def test_okr_audit_row_lands_when_rotator_exhausts(
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, tid, _pw = semi_auto_tenant
    swot_id = await _seed_swot(admin_session, tid)

    async def _fake_load_keys(_session: object, _tid: UUID) -> list[GeminiKey]:
        return [
            GeminiKey(id="fake-id", value="fake-value", label="fake", priority=0),
        ]

    monkeypatch.setattr(
        "imga_api.services.okr_service.load_active_gemini_keys",
        _fake_load_keys,
    )

    async def _fake_rotation(_self: object, _operation: object) -> None:
        raise AllKeysExhaustedError(
            "All LLM keys in rotation failed (504 storm)"
        )

    monkeypatch.setattr(
        "imga_core.llm.key_rotation.GeminiKeyRotator.call_with_rotation",
        _fake_rotation,
    )

    service = OkrService(admin_session, tenant_id=tid, user_id=None)
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        with pytest.raises(AllKeysExhaustedError):
            await service.generate(source_report_id=swot_id)

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(LlmCallAudit)
                .where(LlmCallAudit.tenant_id == tid)
                .where(LlmCallAudit.call_type == "okr")
            )
        ).scalars().all()

    assert len(rows) == 1, (
        f"Exactly one audit row per failed OKR attempt; got "
        f"{len(rows)}. Same regression class as the SWOT test."
    )
    audit = rows[0]
    assert audit.success is False
    assert audit.error_type == "all_keys_exhausted"
    assert audit.model_provider == "gemini"
    assert audit.call_type == "okr"
    assert audit.prompt_template_key == "okr"
    assert audit.related_entity_type == "strategic_report"
    assert audit.related_entity_id == swot_id
