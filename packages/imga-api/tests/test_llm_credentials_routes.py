"""Sprint 8.3.6.5 — tenant LLM credentials route tests.

Six tests pin the security-critical surface:

  * encryption: plaintext lives only in the create request body; DB
    + every response only sees ciphertext / preview.
  * auto-priority: first credential gets 0; subsequent gets max+1.
  * reorder: full ordered list re-assigns priorities 0..N atomically.
  * reorder validation: missing / extra IDs → 400.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import TenantLlmCredential, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_create_credential_encrypts_value_in_db(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
    encryption_helper: Any,  # noqa: ARG001
) -> None:
    """POST encrypts the plaintext key. The DB column never carries
    plaintext; the response only shows the last-4 preview."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)

    plaintext = "AIzaSy-test-key-1234"
    r = batch_client.post(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "Birincil", "api_key": plaintext},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "Birincil"
    assert body["priority"] == 0
    assert body["value_preview"] == "...1234"
    assert plaintext not in r.text  # No plaintext leak in response.

    # Round-trip via DB to confirm the stored value is ciphertext, not
    # plaintext.
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        row = (
            await admin_session.execute(
                select(TenantLlmCredential).where(
                    TenantLlmCredential.id == UUID(body["id"])
                )
            )
        ).scalar_one()
    assert row.encrypted_value != plaintext.encode()
    assert b"AIzaSy" not in row.encrypted_value


@pytest.mark.asyncio
async def test_list_credentials_shows_only_preview(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,  # noqa: ARG001
) -> None:
    """Listing returns preview, never the full key."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    plaintext = "AIzaSy-secret-key-ABCD"
    batch_client.post(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "Birincil", "api_key": plaintext},
    )

    r = batch_client.get(
        "/tenants/me/llm-credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["value_preview"] == "...ABCD"
    assert plaintext not in r.text


@pytest.mark.asyncio
async def test_create_second_credential_sets_priority_one(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,  # noqa: ARG001
) -> None:
    """Second create gets priority = max + 1 = 1."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    r1 = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "Primary", "api_key": "AIzaSy-key-1234"},
    )
    r2 = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "Fallback", "api_key": "AIzaSy-key-5678"},
    )
    assert r1.json()["priority"] == 0
    assert r2.json()["priority"] == 1


@pytest.mark.asyncio
async def test_reorder_updates_priorities(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,  # noqa: ARG001
) -> None:
    """Drag-reorder: full ordered list rewrites priorities 0..N. The
    primary moves to the back."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    a = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "A", "api_key": "AIzaSy-key-AAAA"},
    ).json()
    b = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "B", "api_key": "AIzaSy-key-BBBB"},
    ).json()
    c = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "C", "api_key": "AIzaSy-key-CCCC"},
    ).json()

    # Initial order A=0 / B=1 / C=2. Reorder to C → A → B.
    r = batch_client.put(
        "/tenants/me/llm-credentials/reorder",
        headers=headers,
        json={"ordered_ids": [c["id"], a["id"], b["id"]]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {item["id"]: item for item in body}
    assert by_id[c["id"]]["priority"] == 0
    assert by_id[a["id"]]["priority"] == 1
    assert by_id[b["id"]]["priority"] == 2


@pytest.mark.asyncio
async def test_reorder_with_missing_id_returns_400(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,  # noqa: ARG001
) -> None:
    """Reorder rejects partial lists — caller must include every
    active credential. Missing one would orphan its priority slot."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    a = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "A", "api_key": "AIzaSy-key-AAAA"},
    ).json()
    batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "B", "api_key": "AIzaSy-key-BBBB"},
    )

    r = batch_client.put(
        "/tenants/me/llm-credentials/reorder",
        headers=headers,
        # Only A — B is missing.
        json={"ordered_ids": [a["id"]]},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "reorder_mismatch"


@pytest.mark.asyncio
async def test_delete_credential_removes_row(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    encryption_helper: Any,  # noqa: ARG001
) -> None:
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    headers = {"Authorization": f"Bearer {token}"}

    cred = batch_client.post(
        "/tenants/me/llm-credentials",
        headers=headers,
        json={"label": "X", "api_key": "AIzaSy-key-XXXX"},
    ).json()

    r = batch_client.delete(
        f"/tenants/me/llm-credentials/{cred['id']}",
        headers=headers,
    )
    assert r.status_code == 204

    after = batch_client.get(
        "/tenants/me/llm-credentials",
        headers=headers,
    )
    assert after.status_code == 200
    assert after.json() == []
