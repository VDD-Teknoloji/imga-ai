"""HTTP-call helpers for the E2E flow test.

All helpers are *synchronous* because TestClient is sync — wrapping
them in async would only add ceremony. Each helper either:

  * raises for non-2xx (the "happy path" function), or
  * returns the raw Response (the ``_raw`` variant used when the
    test needs to assert on a specific status code, e.g. 403/401).

The action vocabulary translator (``transition`` family) maps the
verb-style actions in the original E2E spec ("claim", "resolve",
"cancel", "reopen") to the actual ``to_state`` / ``cancellation_reason``
fields the /tickets/{id}/transition endpoint expects. Keeps the test
readable as a narrative.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

# --- auth header ------------------------------------------------------


def auth_header(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --- /auth -----------------------------------------------------------


def login(
    client: TestClient,
    email: str,
    password: str,
    *,
    active_tenant_id: UUID | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"email": email, "password": password}
    if active_tenant_id is not None:
        body["active_tenant_id"] = str(active_tenant_id)
    r = client.post("/auth/login", json=body)
    r.raise_for_status()
    return dict(r.json())


def get_me(client: TestClient, tokens: dict[str, Any]) -> dict[str, Any]:
    r = client.get("/auth/me", headers=auth_header(tokens))
    r.raise_for_status()
    return dict(r.json())


def refresh_raw(client: TestClient, refresh_token: str) -> httpx.Response:
    return client.post("/auth/refresh", json={"refresh_token": refresh_token})


def refresh(client: TestClient, refresh_token: str) -> dict[str, Any]:
    r = refresh_raw(client, refresh_token)
    r.raise_for_status()
    return dict(r.json())


def logout(client: TestClient, refresh_token: str) -> None:
    r = client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert r.status_code == 204, r.text


def switch_tenant(
    client: TestClient, tokens: dict[str, Any], tenant_id: UUID
) -> dict[str, Any]:
    r = client.post(
        "/auth/switch-tenant",
        headers=auth_header(tokens),
        json={"tenant_id": str(tenant_id)},
    )
    r.raise_for_status()
    return dict(r.json())


# --- /tenants/me/* ---------------------------------------------------


def set_automation_mode(
    client: TestClient, tokens: dict[str, Any], mode: str
) -> None:
    r = client.patch(
        "/tenants/me/automation-mode",
        headers=auth_header(tokens),
        json={"automation_mode": mode},
    )
    assert r.status_code == 204, r.text


def list_categories(
    client: TestClient, tokens: dict[str, Any]
) -> list[dict[str, Any]]:
    r = client.get("/tenants/me/categories", headers=auth_header(tokens))
    r.raise_for_status()
    return list(r.json()["categories"])


def toggle_category(
    client: TestClient,
    tokens: dict[str, Any],
    category_id: UUID | str,
    *,
    enabled: bool,
) -> None:
    r = client.patch(
        f"/tenants/me/categories/{category_id}",
        headers=auth_header(tokens),
        json={"is_enabled": enabled},
    )
    assert r.status_code == 204, r.text


def create_custom_category(
    client: TestClient,
    tokens: dict[str, Any],
    *,
    code: str,
    label_tr: str,
    label_en: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "label_tr": label_tr}
    if label_en is not None:
        payload["label_en"] = label_en
    r = client.post(
        "/tenants/me/custom-categories",
        headers=auth_header(tokens),
        json=payload,
    )
    r.raise_for_status()
    return dict(r.json())


def find_category_id(categories: list[dict[str, Any]], code: str) -> UUID:
    """Tiny helper so the test reads ``find_category_id(cats, 'kargo')``
    rather than rebuilding the comprehension each time."""
    for c in categories:
        if c["code"] == code:
            return UUID(str(c["id"]))
    raise LookupError(f"category {code!r} not found in list")


# --- /tickets ---------------------------------------------------------


def create_ticket(
    client: TestClient,
    tokens: dict[str, Any],
    *,
    category_id: UUID,
    title: str,
    summary: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "category_id": str(category_id),
        "title": title,
    }
    if summary is not None:
        body["summary"] = summary
    r = client.post("/tickets", headers=auth_header(tokens), json=body)
    r.raise_for_status()
    return dict(r.json())


def list_tickets(client: TestClient, tokens: dict[str, Any]) -> dict[str, Any]:
    r = client.get("/tickets", headers=auth_header(tokens))
    r.raise_for_status()
    return dict(r.json())


def list_tickets_raw(
    client: TestClient, tokens: dict[str, Any]
) -> httpx.Response:
    return client.get("/tickets", headers=auth_header(tokens))


def get_timeline(
    client: TestClient, tokens: dict[str, Any], ticket_id: UUID | str
) -> dict[str, Any]:
    r = client.get(
        f"/tickets/{ticket_id}/transitions",
        headers=auth_header(tokens),
    )
    r.raise_for_status()
    return dict(r.json())


def quick_resolve(
    client: TestClient, tokens: dict[str, Any], ticket_id: UUID | str
) -> dict[str, Any]:
    r = client.post(
        f"/tickets/{ticket_id}/quick-resolve",
        headers=auth_header(tokens),
    )
    r.raise_for_status()
    return dict(r.json())


# --- transition vocabulary translator -------------------------------

# Maps narrative-style actions ("claim", "cancel", "reopen") to the
# actual to_state values the /tickets/{id}/transition endpoint expects.
# Keeps the E2E test reading like a story.
_ACTION_TO_STATE: dict[str, str] = {
    "claim": "in_progress",
    "wait_customer": "pending_customer",
    "resume": "in_progress",
    "resolve": "resolved",
    "close": "closed",
    "cancel": "cancelled",
    "uncancel": "open",
    "reopen": "open",
    "unclaim": "open",
}


def transition_raw(
    client: TestClient,
    tokens: dict[str, Any],
    ticket_id: UUID | str,
    action: str,
    *,
    cancellation_reason: str | None = None,
    reason: str | None = None,
) -> httpx.Response:
    if action not in _ACTION_TO_STATE:
        raise ValueError(f"unknown ticket action {action!r}")
    body: dict[str, Any] = {"to_state": _ACTION_TO_STATE[action]}
    if cancellation_reason is not None:
        body["cancellation_reason"] = cancellation_reason
    if reason is not None:
        body["reason"] = reason
    return client.post(
        f"/tickets/{ticket_id}/transition",
        headers=auth_header(tokens),
        json=body,
    )


def transition(
    client: TestClient,
    tokens: dict[str, Any],
    ticket_id: UUID | str,
    action: str,
    *,
    cancellation_reason: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    r = transition_raw(
        client,
        tokens,
        ticket_id,
        action,
        cancellation_reason=cancellation_reason,
        reason=reason,
    )
    r.raise_for_status()
    return dict(r.json())
