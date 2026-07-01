"""İmga v1 — CANLI kara-kutu contract testi (contract §11 / goal §2.3, §3.10).

imga fixture'ı GEREKTİRMEZ — sadece çalışan bir endpoint (IMGA_BASE_URL) + geçerli
bir tenant token (IMGA_TENANT_TOKEN) ile HTTP üzerinden §11 kriterlerini doğrular.
AsakAI nightly CI bunu staging'e karşı koşar; 7 ardışık gün yeşil = §2 kriter 3.

IMGA_BASE_URL set değilse TÜM testler skip → :5433 birim suite'inde inert kalır
(canonical pytest listesine EKLENMEZ; nightly CI ayrı env ile koşar).

Env:
  IMGA_BASE_URL       — örn. https://api-staging.imga.ai   (zorunlu; yoksa skip)
  IMGA_TENANT_TOKEN   — imga_stg_… / imga_live_… tenant Bearer  (analyze/data testleri)
  IMGA_TENANT_ID      — örn. asakai-staging
  IMGA_WRONG_ENV_TOKEN— karşı-ortam önekli token (ör. staging'e imga_live_)  (opsiyonel)
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

BASE = os.environ.get("IMGA_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("IMGA_TENANT_TOKEN", "")
TENANT_ID = os.environ.get("IMGA_TENANT_ID", "asakai-staging")
WRONG_ENV_TOKEN = os.environ.get("IMGA_WRONG_ENV_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not BASE, reason="IMGA_BASE_URL yok — canlı contract testi yalnız nightly CI'da"
)

_TIMEOUT = httpx.Timeout(35.0)


def _needs_token() -> None:
    if not TOKEN:
        pytest.skip("IMGA_TENANT_TOKEN yok")


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _free_analyze_body(client_request_id: str | None = None) -> dict:
    return {
        "tenant_id": TENANT_ID,
        "use_case": "free-analyze",
        "period": "custom",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "context": {"source": "nightly-contract"},
        "user_prompt": "Kısa bir sistem testi cevabı ver.",
        "language": "tr",
        "client_request_id": client_request_id or str(uuid.uuid4()),
    }


# --- §11: health (unauth) --------------------------------------------------


def test_health_shape() -> None:
    r = httpx.get(f"{BASE}/v1/health", timeout=_TIMEOUT)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded", "down"}
    assert "version" in body
    assert body["region"] == "outbound"  # v1.3 residency düz
    assert isinstance(body["providers"], list) and body["providers"]
    p = body["providers"][0]
    assert p["zone"] == "outbound" and isinstance(p["healthy"], bool)


# --- §11: envelope shape + residency + header matrisi ----------------------


def test_analyze_envelope_and_headers() -> None:
    _needs_token()
    r = httpx.post(
        f"{BASE}/v1/analyze/free-analyze",
        headers=_auth(),
        json=_free_analyze_body(),
        timeout=_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["request_id"]
    meta = body["meta"]
    # §3 zarf: nested tokens, opak/açık model, residency outbound
    assert set(meta["tokens"]) == {"prompt", "completion", "total"}
    assert meta["processed_in"] == "outbound"
    assert "model" in meta and "cost_try" in meta and meta["cached"] is False
    # §3.6 header matrisi (her yanıtta)
    for h in (
        "X-Imga-Request-Id",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-Quota-Tokens-Remaining",
        "X-Quota-Reset",
    ):
        assert h in r.headers, f"eksik header: {h}"


# --- §11: error taxonomy (AnalyzeError shape) ------------------------------


def _assert_analyze_error(r: httpx.Response, code: str) -> None:
    body = r.json()
    assert body["ok"] is False
    assert body["request_id"]
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def test_error_missing_user_prompt() -> None:
    _needs_token()
    body = _free_analyze_body()
    del body["user_prompt"]
    r = httpx.post(
        f"{BASE}/v1/analyze/free-analyze",
        headers=_auth(),
        json=body,
        timeout=_TIMEOUT,
    )
    assert r.status_code == 400
    _assert_analyze_error(r, "invalid_input")


def test_error_unknown_use_case() -> None:
    _needs_token()
    r = httpx.post(
        f"{BASE}/v1/analyze/not-a-use-case",
        headers=_auth(),
        json=_free_analyze_body(),
        timeout=_TIMEOUT,
    )
    assert r.status_code == 400
    _assert_analyze_error(r, "invalid_input")


def test_error_auth_failed_no_token() -> None:
    r = httpx.post(
        f"{BASE}/v1/analyze/free-analyze",
        headers={"Content-Type": "application/json"},
        json=_free_analyze_body(),
        timeout=_TIMEOUT,
    )
    assert r.status_code == 401
    _assert_analyze_error(r, "auth_failed")


def test_error_export_window_too_large() -> None:
    _needs_token()
    r = httpx.get(
        f"{BASE}/v1/data/export",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"from": "2026-01-01T00:00:00", "to": "2026-06-01T00:00:00"},
        timeout=_TIMEOUT,
    )
    assert r.status_code == 400
    _assert_analyze_error(r, "export_window_too_large")


# --- §11: idempotency replay -----------------------------------------------


def test_idempotency_replay() -> None:
    _needs_token()
    crid = str(uuid.uuid4())
    body = _free_analyze_body(client_request_id=crid)
    r1 = httpx.post(
        f"{BASE}/v1/analyze/free-analyze",
        headers=_auth(),
        json=body,
        timeout=_TIMEOUT,
    )
    assert r1.status_code == 200, r1.text
    r2 = httpx.post(
        f"{BASE}/v1/analyze/free-analyze",
        headers=_auth(),
        json=body,
        timeout=_TIMEOUT,
    )
    assert r2.status_code == 200
    b1, b2 = r1.json(), r2.json()
    # Aynı client_request_id → byte-identical response + cached:true + header
    assert b2["request_id"] == b1["request_id"]
    assert b2["response"] == b1["response"]
    assert b2["meta"]["tokens"] == b1["meta"]["tokens"]
    assert b2["meta"]["cached"] is True
    assert r2.headers.get("Idempotency-Replayed") == "true"


# --- §11: cross-env prefix rejection (opsiyonel — karşı-ortam token gerekir) ---


def test_cross_env_prefix_rejected() -> None:
    if not WRONG_ENV_TOKEN:
        pytest.skip("IMGA_WRONG_ENV_TOKEN yok — cross-env testi atlandı")
    r = httpx.post(
        f"{BASE}/v1/analyze/free-analyze",
        headers={
            "Authorization": f"Bearer {WRONG_ENV_TOKEN}",
            "Content-Type": "application/json",
        },
        json=_free_analyze_body(),
        timeout=_TIMEOUT,
    )
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "auth_failed"
    assert (body["error"].get("details") or {}).get("hint") == "wrong_environment"
