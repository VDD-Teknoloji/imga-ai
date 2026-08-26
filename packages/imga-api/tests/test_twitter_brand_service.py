"""2026-08-26 — Twitter'dan Çek AI katmanı (services/twitter_brand_service).

Gerçek LLM yok: onboarding testlerindeki desenle GeminiProvider'ın
ödünç alınan ``generate_root_cause`` yöntemi AsyncMock'lanır. Kapsam:
  * birim — sanitize/compose/normalize_handle, plan normalizasyonu,
    hakem cevabı indeks eşlemesi (fail-open)
  * servis — plan çağrısı (denetim satırı twitter_keywords), hakem
    partileme + eşzamanlılık + parti hatası fail-open (twitter_relevance),
    anahtar yokken NoCredentialsError
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from imga_core.llm import LLMProviderError
from imga_db.models import LlmCallAudit, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.twitter_brand_service import (
    BrandPlanError,
    compose_term,
    judge_tweet_relevance,
    normalize_handle,
    normalize_plan_response,
    parse_judge_response,
    plan_brand_search,
    sanitize_term,
)
from imga_api.services.twitter_import import build_search_query, parse_search_terms

_SET_TENANT = "SELECT set_config('app.current_tenant_id', :t, true)"


async def _bind(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(text(_SET_TENANT), {"t": str(tenant_id)})


def _mock_provider(
    *,
    payload: dict[str, Any] | None = None,
    side_effect: Any = None,
) -> Any:
    from imga_core.llm.gemini import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    if side_effect is not None:
        provider.generate_root_cause = AsyncMock(side_effect=side_effect)  # type: ignore[method-assign]
    else:
        provider.generate_root_cause = AsyncMock(  # type: ignore[method-assign]
            return_value=(payload or {}, {"input": 10, "output": 5})
        )
    return provider


# --- birim ----------------------------------------------------------------


def test_sanitize_term_strips_quotes_commas_and_leading_dash() -> None:
    assert sanitize_term(' "karaca, tencere" ') == "karaca tencere"
    assert sanitize_term("--cem karaca") == "cem karaca"
    assert sanitize_term("k") is None
    assert sanitize_term(None) is None
    assert len(sanitize_term("x" * 200) or "") == 60


def test_compose_term_round_trips_through_parse_search_terms() -> None:
    term = compose_term(["karaca tencere", "@karacaonline"], ["cem karaca", "hidayet karaca"])
    assert term == "karaca tencere, @karacaonline, -cem karaca, -hidayet karaca"
    parsed = parse_search_terms(term)
    assert parsed.positive == ("karaca tencere", "@karacaonline")
    assert parsed.negative == ("cem karaca", "hidayet karaca")


def test_normalize_handle() -> None:
    assert normalize_handle(" @KaracaOnline ") == "KaracaOnline"
    assert normalize_handle("") is None
    assert normalize_handle("iki kelime") is None


def test_normalize_plan_response_caps_dedupes_and_prefers_user_handle() -> None:
    data = {
        "brand_summary": "  Karaca  ev eşyası markası. ",
        "include": ["Karaca", "karaca", "karaca tencere", '"karaca, çaydanlık"']
        + [f"ürün {i}" for i in range(10)],
        "exclude": ["Cem Karaca", "karaca tencere", "-Hidayet Karaca"]
        + [f"ad {i}" for i in range(20)],
        "handle": "@llmtahmini",
        "bare_name_ambiguous": True,
        "notes": "Soyadı olarak yaygın.",
    }
    plan = normalize_plan_response(data, brand="Karaca", handle="karacaonline")
    assert plan.include[:3] == ["Karaca", "karaca tencere", "karaca çaydanlık"]
    assert len(plan.include) == 8
    # include'da olan terim exclude'dan düşer; baştaki '-' temizlenir.
    assert "karaca tencere" not in plan.exclude
    assert plan.exclude[:2] == ["Cem Karaca", "Hidayet Karaca"]
    assert len(plan.exclude) <= 15
    assert plan.handle == "karacaonline"
    assert plan.brand_summary == "Karaca ev eşyası markası."
    assert plan.bare_name_ambiguous is True
    assert plan.notes == "Soyadı olarak yaygın."


def test_normalize_plan_response_falls_back_to_brand_when_include_empty() -> None:
    plan = normalize_plan_response({"include": [], "exclude": []}, brand="Navlungo", handle=None)
    assert plan.include == ["Navlungo"]
    assert plan.handle is None


def test_build_search_query_trims_negatives_to_length_limit() -> None:
    exclude = [f"gereksiz negatif terim {i}" for i in range(40)]
    q = build_search_query(compose_term(["karaca tencere"], exclude), "karacaonline")
    assert len(q) <= 500
    assert q.startswith('"karaca tencere" -"gereksiz negatif terim 0"')
    assert q.endswith("-from:karacaonline lang:tr -filter:retweets")


def test_parse_judge_response_maps_by_index_and_fails_open() -> None:
    data = {
        "verdicts": [
            {"i": 26, "relevant": False},
            {"i": 27, "relevant": True},
            {"i": 99, "relevant": False},  # aralık dışı → yok sayılır
            {"i": "28", "relevant": False},  # bozuk → yok sayılır
            "çöp",
        ]
    }
    assert parse_judge_response(data, start_index=26, size=4) == [False, True, True, True]
    assert parse_judge_response(None, start_index=1, size=2) == [True, True]
    assert parse_judge_response({"verdicts": "x"}, start_index=1, size=1) == [True]


# --- servis ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_brand_search_writes_audit_row(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "sk-or-platform")
    monkeypatch.setenv("IMGA_PLATFORM_LLM_MODEL", "z-ai/glm-5.2")
    provider = _mock_provider(
        payload={
            "brand_summary": "Karaca züccaciye ve ev tekstili markası.",
            "include": ["karaca tencere", "@karacaonline"],
            "exclude": ["cem karaca"],
            "handle": "karacaonline",
            "bare_name_ambiguous": True,
        }
    )
    async with admin_session.begin():
        await _bind(admin_session, tid)
        plan = await plan_brand_search(
            admin_session,
            tid,
            brand="Karaca",
            handle=None,
            actor_user_id=None,
            provider=provider,
        )
    assert plan.include == ["karaca tencere", "@karacaonline"]
    assert plan.exclude == ["cem karaca"]
    assert plan.handle == "karacaonline"
    kwargs = provider.generate_root_cause.await_args.kwargs
    assert kwargs["model_name"] == "z-ai/glm-5.2"
    assert 'Marka / arama adı: "Karaca"' in kwargs["user_prompt"]

    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            (
                await admin_session.execute(
                    select(LlmCallAudit).where(
                        LlmCallAudit.tenant_id == tid,
                        LlmCallAudit.call_type == "twitter_keywords",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].success is True
    assert rows[0].model_provider == "openrouter"


@pytest.mark.asyncio
async def test_plan_brand_search_raises_without_keys(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.delenv("IMGA_PLATFORM_LLM_KEY", raising=False)
    # pytest.raises transaction'ın İÇİNDE (test_onboarding deseni): istisna
    # begin()'den dışarı sızarsa rollback + expire → teardown MissingGreenlet.
    async with admin_session.begin():
        await _bind(admin_session, tid)
        with pytest.raises(NoCredentialsError):
            await plan_brand_search(
                admin_session,
                tid,
                brand="Karaca",
                handle=None,
                actor_user_id=None,
                provider=_mock_provider(payload={"include": ["karaca"], "exclude": []}),
            )


@pytest.mark.asyncio
async def test_plan_brand_search_llm_failure_is_brand_plan_error_and_audited(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "sk-or-platform")
    provider = _mock_provider(side_effect=LLMProviderError("boom"))
    # Başarısızlık denetim satırı istisnadan ÖNCE yazılır; transaction
    # commit etsin diye pytest.raises içeride (route da aynı şekilde
    # BrandPlanError'ı transaction içinde yakalar).
    async with admin_session.begin():
        await _bind(admin_session, tid)
        with pytest.raises(BrandPlanError):
            await plan_brand_search(
                admin_session,
                tid,
                brand="Karaca",
                handle=None,
                actor_user_id=None,
                provider=provider,
            )
    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            (
                await admin_session.execute(
                    select(LlmCallAudit).where(
                        LlmCallAudit.tenant_id == tid,
                        LlmCallAudit.call_type == "twitter_keywords",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].success is False


@pytest.mark.asyncio
async def test_judge_batches_concurrently_and_fails_open_per_batch(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tid, _ = semi_auto_tenant
    monkeypatch.setenv("IMGA_PLATFORM_LLM_KEY", "sk-or-platform")
    tweets = [f"gönderi {i}" for i in range(1, 8)]  # 3 parti (3+3+1)
    seen_prompts: list[str] = []

    async def fake_generate(**kwargs: Any) -> tuple[dict[str, Any], dict[str, int] | None]:
        prompt = kwargs["user_prompt"]
        seen_prompts.append(prompt)
        await asyncio.sleep(0)
        if "4. gönderi 4" in prompt:
            raise LLMProviderError("parti 2 çöktü")
        if "1. gönderi 1" in prompt:
            return {"verdicts": [{"i": 1, "relevant": False}, {"i": 3, "relevant": False}]}, None
        return {"verdicts": [{"i": 7, "relevant": False}]}, {"input": 3, "output": 1}

    provider = _mock_provider()
    provider.generate_root_cause = AsyncMock(side_effect=fake_generate)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        verdict = await judge_tweet_relevance(
            admin_session,
            tid,
            brand="karaca",
            brand_summary="Ev eşyası markası.",
            include=["karaca"],
            exclude=["cem karaca"],
            handle="karacaonline",
            tweets=tweets,
            actor_user_id=None,
            provider=provider,
            batch_size=3,
            concurrency=2,
        )
    # parti 1: 1 ve 3 elendi; parti 2 hata → hepsi tutuldu; parti 3: 7 elendi
    assert verdict.relevant == [False, True, False, True, True, True, False]
    assert verdict.batches == 3
    assert verdict.failed_batches == 1
    assert verdict.dropped == 3
    assert any("Marka özeti: Ev eşyası markası." in p for p in seen_prompts)
    assert any("Resmi X hesabı: @karacaonline" in p for p in seen_prompts)

    async with admin_session.begin():
        await _bind(admin_session, tid)
        rows = (
            (
                await admin_session.execute(
                    select(LlmCallAudit).where(
                        LlmCallAudit.tenant_id == tid,
                        LlmCallAudit.call_type == "twitter_relevance",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3
    assert sorted(r.success for r in rows) == [False, True, True]


@pytest.mark.asyncio
async def test_judge_empty_input_is_noop(
    admin_session: AsyncSession,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    _, tid, _ = semi_auto_tenant
    async with admin_session.begin():
        await _bind(admin_session, tid)
        verdict = await judge_tweet_relevance(
            admin_session,
            tid,
            brand="x",
            brand_summary=None,
            include=[],
            exclude=[],
            handle=None,
            tweets=[],
            actor_user_id=None,
            provider=_mock_provider(),
        )
    assert verdict.relevant == [] and verdict.batches == 0
