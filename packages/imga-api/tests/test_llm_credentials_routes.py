"""Kurum tarafi LLM kimlik yuzeyi — 2026-08-09 sonrasi salt-okur.

Model / API anahtari yonetimi super-admin'e tasindi
(``test_admin_llm_credentials.py`` o yuzeyi kapsar). Burada kalan
sozlesme:

  * GET liste her uye rolune acik ve yalniz maskeli onizleme doner.
  * GET /openrouter-models katalogu okunabilir kalir.
  * Yazma uclari router'dan KALDIRILDI — POST 405 (ayni yolda GET
    duruyor), PATCH / PUT reorder / DELETE 404 (o yol sablonlarinda
    hicbir metot kalmadi). Bu testler yazma yolunun geri sizmasini
    yakalar.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User

from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_list_credentials_shows_only_preview(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    encryption_helper: Any,
) -> None:
    """Listeleme onizleme doner, tam anahtari asla."""
    user, tid, pw = semi_auto_tenant
    plaintext = "AIzaSy-secret-key-ABCD"
    await mock_gemini_credential(tid, plaintext, label="Birincil")

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["label"] == "Birincil"
    assert body[0]["value_preview"] == "...ABCD"
    assert plaintext not in r.text


@pytest.mark.asyncio
async def test_list_orders_by_priority(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    encryption_helper: Any,
) -> None:
    """Sira oncelige gore — kazanan saglayici listede en ustte gorunur
    ki kurum hangi yapilandirmanin canli oldugunu okuyabilsin."""
    user, tid, pw = semi_auto_tenant
    await mock_gemini_credential(
        tid, "AIzaSy-key-1111", label="Yedek", priority=1
    )
    await mock_gemini_credential(
        tid, "sk-or-key-2222", label="Birincil",
        provider="openrouter", priority=0,
    )

    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["label"] for c in body] == ["Birincil", "Yedek"]
    assert body[0]["provider"] == "openrouter"


@pytest.mark.asyncio
async def test_create_endpoint_removed_returns_405(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,
) -> None:
    """POST kaldirildi. Ayni yolda GET durdugu icin router 405 doner —
    404 degil."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "Birincil", "api_key": "AIzaSy-test-key-1234"},
    )
    assert r.status_code == 405, r.text


@pytest.mark.asyncio
async def test_update_endpoint_removed_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    encryption_helper: Any,
) -> None:
    user, tid, pw = semi_auto_tenant
    cred_id = await mock_gemini_credential(tid, "AIzaSy-key-1234")
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.patch(
        f"/tenants/me/llm-credentials/{cred_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_reorder_endpoint_removed_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    encryption_helper: Any,
) -> None:
    user, tid, pw = semi_auto_tenant
    cred_id = await mock_gemini_credential(tid, "AIzaSy-key-1234")
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.put(
        "/tenants/me/llm-credentials/reorder",
        headers={"Authorization": f"Bearer {token}"},
        json={"ordered_ids": [str(cred_id)]},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_delete_endpoint_removed_returns_404(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    mock_gemini_credential: Any,
    encryption_helper: Any,
) -> None:
    user, tid, pw = semi_auto_tenant
    cred_id = await mock_gemini_credential(tid, "AIzaSy-key-1234")
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.delete(
        f"/tenants/me/llm-credentials/{cred_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, r.text

    # Kayit yerinde durmali — 404 "silindi ama bulunamadi" degil,
    # "boyle bir uc yok" demek.
    listed = batch_client.get(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert [UUID(c["id"]) for c in listed] == [cred_id]


@pytest.mark.asyncio
async def test_unknown_tenant_write_path_is_not_reachable(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,
) -> None:
    """Kurum yolunda hicbir yazma sablonu kalmadi — uydurma bir id ile
    de olsa PATCH/DELETE rota bulamaz."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}
    ghost = uuid4()
    assert batch_client.patch(
        f"/tenants/me/llm-credentials/{ghost}", headers=headers, json={},
    ).status_code == 404
    assert batch_client.delete(
        f"/tenants/me/llm-credentials/{ghost}", headers=headers,
    ).status_code == 404
