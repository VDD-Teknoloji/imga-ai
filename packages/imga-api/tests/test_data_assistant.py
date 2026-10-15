"""Veri asistanı (2026-10-15): soru ayrıştırma (saf), kanıt paketi ve
/tenants/me/assistant uçları.

LLM yolu sağlayıcı sahtesiyle (``GeminiProvider.__new__`` + AsyncMock,
test_root_cause.py deseni) ve ``mock_gemini_credential`` ile; anahtarsız
kurumda kural tabanlı yanıt (``llm_used=False``) doğrulanır.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core import review_text_hash
from imga_core.llm.gemini import GeminiProvider
from imga_db.models import Review, ReviewDecision, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.services import data_assistant_service as das
from imga_api.services.data_assistant_service import parse_question
from tests.batch_helpers import login_token

TODAY = date(2026, 10, 15)
CODES = {"kargo", "iade", "faturalama", "teknik_destek", "musteri_hizmetleri", "belirsiz"}


# --- parse_question (saf) ----------------------------------------------------


def test_parse_question_default_window_and_focus() -> None:
    scope = parse_question("Son 1 ayda iadeler neden arttı?", today=TODAY, valid_codes=CODES)
    assert scope.window_days == 30 and scope.period_label == "Son 1 ay"
    assert scope.date_to == TODAY and scope.date_from == TODAY - timedelta(days=29)
    assert scope.prev_to == scope.date_from - timedelta(days=1)
    assert (scope.prev_to - scope.prev_from).days == 29
    assert scope.focus_category == "iade"
    assert scope.focus_category_label == das._CATEGORY_LABELS["iade"]
    assert scope.focus_sentiment == "NEGATIF"
    assert scope.focus_stage is None


@pytest.mark.parametrize(
    ("question", "days", "category", "stage"),
    [
        ("Kargo şikayetleri son 2 haftada nasıl?", 14, "kargo", None),
        ("Son 90 gün fatura sorunları", 90, "faturalama", None),
        ("Ayrılmak isteyen müşteriler ne diyor?", 30, None, "ayrilma"),
        ("Uygulama hataları son üç ayda arttı mı", 90, "teknik_destek", None),
        ("Genel durum nedir", 30, None, None),
    ],
)
def test_parse_question_variants(
    question: str, days: int, category: str | None, stage: str | None
) -> None:
    scope = parse_question(question, today=TODAY, valid_codes=CODES)
    assert scope.window_days == days
    assert scope.focus_category == category
    assert scope.focus_stage == stage


def test_parse_question_ignores_codes_outside_tenant() -> None:
    # "iade" kurumun kod listesinde yoksa odak kurulmaz.
    scope = parse_question("iadeler neden arttı", today=TODAY, valid_codes={"kargo"})
    assert scope.focus_category is None
    custom = parse_question(
        "Mağaza deneyimi kötü",
        today=TODAY,
        valid_codes={"magaza"},
        custom_labels={"magaza": "Mağaza"},
    )
    assert custom.focus_category == "magaza"


# --- e2e -----------------------------------------------------------------------


async def _seed(session: AsyncSession, tenant_id: UUID) -> None:
    now = datetime.now(UTC)
    async with session.begin():
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        rows: list[tuple[str, str, int, str, str | None, str | None]] = []
        # Sorulan dönem (son 30 gün): 6 iade (5 olumsuz) + 2 kargo.
        for i in range(6):
            rows.append(
                (
                    f"İade talebim {i} gündür sonuçlanmadı, para iadesi gelmedi",
                    "iade",
                    3 + i,
                    "NEGATIF" if i < 5 else "NÖTR",
                    "ayrilma" if i == 0 else "destek",
                    "Email",
                )
            )
        rows.append(("Kargo geç geldi", "kargo", 4, "NEGATIF", "teslimat", "twitter"))
        rows.append(("Kargo zamanında geldi", "kargo", 6, "POZITIF", "teslimat", "twitter"))
        # Önceki dönem: 2 iade.
        rows.append(("İade süreci yavaştı", "iade", 40, "NEGATIF", "destek", "Email"))
        rows.append(("İade kabul edildi, teşekkürler", "iade", 45, "POZITIF", "sadakat", "Email"))
        for text_value, category, days_ago, label, stage, source in rows:
            when = now - timedelta(days=days_ago)
            session.add(
                Review(
                    tenant_id=tenant_id,
                    text=text_value,
                    text_hash=review_text_hash(text_value + str(days_ago)),
                    sentiment_label=label,
                    sentiment_score=-0.6
                    if label == "NEGATIF"
                    else (0.6 if label == "POZITIF" else 0.0),
                    primary_category=category,
                    primary_confidence=0.9,
                    automation_mode="semi_auto",
                    decision=ReviewDecision.SKIPPED_THRESHOLD,
                    analyzed_at=when,
                    review_date=when,
                    journey_stage=stage,
                    source=source,
                )
            )


def _mock_provider(payload: dict[str, Any]) -> GeminiProvider:
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.generate_assistant_answer = AsyncMock(  # type: ignore[method-assign]
        return_value=(payload, {"input": 100, "output": 50})
    )
    return provider


@pytest.mark.asyncio
async def test_ask_without_llm_keys_returns_rule_based_evidence(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(admin_session, tid)
    # Platform yedek anahtarı da yok → kural tabanlı yol.
    monkeypatch.setattr(das, "platform_fallback_selection", lambda: None)
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = batch_client.post(
        "/tenants/me/assistant/ask",
        json={"question": "Son 1 ayda iadeler neden arttı?"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_used"] is False and body["model"] is None
    assert body["scope"]["focus_category"] == "iade"
    evidence = body["evidence"]
    assert evidence["current"]["focus"]["total"] == 6
    assert evidence["current"]["focus"]["negatif"] == 5
    assert evidence["previous"]["focus"]["total"] == 2
    assert evidence["focus_delta"]["total_diff"] == 4
    assert evidence["focus_delta"]["total_pct_change"] == 200.0
    assert evidence["current"]["total"] == 8 and evidence["previous"]["total"] == 2
    assert evidence["stage_delta"]["ayrilma"] == {"current": 1, "previous": 0}
    assert evidence["category_movers"][0]["code"] == "iade"
    # Alıntılar yalnız odak + olumsuz; KVKK maskesi ve ref numarası.
    assert 1 <= len(evidence["quotes"]) <= 5
    assert all(
        q["category"] == das._CATEGORY_LABELS["iade"] and q["sentiment"] == "NEGATIF"
        for q in evidence["quotes"]
    )
    assert evidence["quotes"][0]["ref"] == 1
    assert "6 yorum" in body["answer"] and "arttı" in body["answer"]
    assert any("LLM anahtarı" in gap for gap in body["data_gaps"])

    s = batch_client.get("/tenants/me/assistant/suggestions", headers=headers)
    assert s.status_code == 200, s.text
    items = s.json()["items"]
    assert items and items[0].startswith("Son 1 ayda") and len(items) <= 6

    bad = batch_client.post("/tenants/me/assistant/ask", json={"question": "   "}, headers=headers)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_ask_with_llm_uses_provider_and_audits(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    mock_gemini_credential: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, tid, pw = semi_auto_tenant
    await _seed(admin_session, tid)
    await mock_gemini_credential(tid, "fake-key-for-assistant-123")
    provider = _mock_provider(
        {
            "answer": "İade yorumları 2'den 6'ya çıktı; 5'i olumsuz [#1].",
            "highlights": ["İade +4", "Ayrılma riski 1"],
            "follow_ups": ["Hangi kanal?"],
            "data_gaps": [],
        }
    )
    monkeypatch.setattr(das, "build_structured_provider", lambda _name: provider)
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r = batch_client.post(
        "/tenants/me/assistant/ask",
        json={
            "question": "Son 1 ayda iadeler neden arttı?",
            "history": [{"role": "user", "content": "merhaba"}],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["llm_used"] is True and body["provider"] == "gemini"
    assert body["answer"].startswith("İade yorumları")
    assert body["highlights"] == ["İade +4", "Ayrılma riski 1"]
    call = provider.generate_assistant_answer.await_args  # type: ignore[attr-defined]
    assert call is not None
    prompt = call.kwargs["user_prompt"]
    assert "KANIT PAKETİ" in prompt and '"focus_category": "iade"' in prompt
    assert "merhaba" in prompt
    assert "rakamlara sadık" in call.kwargs["system_prompt"]

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tid)}
        )
        row = (
            await admin_session.execute(
                text(
                    "SELECT call_type, error_type, output_tokens FROM llm_call_audit "
                    "WHERE tenant_id = :t AND call_type = 'assistant'"
                ),
                {"t": str(tid)},
            )
        ).first()
    assert row is not None and row[1] is None and row[2] == 50
