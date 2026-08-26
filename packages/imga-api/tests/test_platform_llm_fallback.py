"""2026-08-26 — platform düzeyi LLM anahtar yedeği.

Vaka: yeni açılan kurumda (Karaca Home KSA) Twitter'dan Çek işi
"kurumda aktif LLM anahtarı yok" ile düştü. Kural: kurumun kendi aktif
kaydı yoksa IMGA_PLATFORM_LLM_KEY devreye girer; kayıt varsa kurum
kazanır; ikisi de yoksa None (eski davranış).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from imga_db.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.llm_credentials import (
    PLATFORM_KEY_ID,
    PLATFORM_KEY_LABEL,
    load_active_llm_keys,
    mark_keys_failed,
    platform_fallback_selection,
)

_SET_TENANT = "SELECT set_config('app.current_tenant_id', :t, true)"


async def _bind(session: AsyncSession, tenant_id: UUID) -> None:
    from sqlalchemy import text

    await session.execute(text(_SET_TENANT), {"t": str(tenant_id)})


@pytest.mark.asyncio
async def test_no_rows_no_env_returns_none(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.delenv("IMGA_PLATFORM_LLM_KEY", raising=False)
    async with admin_session.begin():
        await _bind(admin_session, tid)
        assert await load_active_llm_keys(admin_session, tid) is None


@pytest.mark.asyncio
async def test_no_rows_uses_platform_fallback(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "sk-or-platform-XYZ")
    monkeypatch.setenv("IMGA_PLATFORM_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("IMGA_PLATFORM_LLM_MODEL", "z-ai/glm-5.2")
    async with admin_session.begin():
        await _bind(admin_session, tid)
        sel = await load_active_llm_keys(admin_session, tid)
    assert sel is not None
    assert sel.provider == "openrouter"
    assert sel.model == "z-ai/glm-5.2"
    assert len(sel.keys) == 1
    assert sel.keys[0].value == "sk-or-platform-XYZ"
    assert sel.keys[0].label == PLATFORM_KEY_LABEL
    # Cagiranlar UUID(k.id) yapar — sabit kimlik gecerli UUID olmali.
    assert UUID(sel.keys[0].id) == PLATFORM_KEY_ID


@pytest.mark.asyncio
async def test_tenant_rows_win_over_platform_fallback(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    encryption_helper: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "sk-or-platform-XYZ")
    await mock_gemini_credential(
        tid, "sk-or-tenant-1111", label="Kurum", provider="openrouter",
        priority=0,
    )
    async with admin_session.begin():
        await _bind(admin_session, tid)
        sel = await load_active_llm_keys(admin_session, tid)
    assert sel is not None
    assert sel.provider == "openrouter"
    assert [k.value for k in sel.keys] == ["sk-or-tenant-1111"]
    assert sel.keys[0].label == "Kurum"


def test_platform_fallback_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "  sk-or-x  ")
    monkeypatch.delenv("IMGA_PLATFORM_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("IMGA_PLATFORM_LLM_MODEL", raising=False)
    sel = platform_fallback_selection()
    assert sel is not None
    assert sel.provider == "openrouter"
    assert sel.model is None
    assert sel.keys[0].value == "sk-or-x"
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "   ")
    assert platform_fallback_selection() is None


@pytest.mark.asyncio
async def test_mark_keys_failed_skips_platform_sentinel(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    _, tid, _ = semi_auto_tenant
    async with admin_session.begin():
        await _bind(admin_session, tid)
        # Sabit kimlik DB'de yok; UPDATE hicbir satira dokunmadan
        # ve hata firlatmadan doner.
        await mark_keys_failed(admin_session, [PLATFORM_KEY_ID])
