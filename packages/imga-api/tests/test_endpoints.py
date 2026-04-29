"""Endpoint tests using the stubbed pipeline (no BERT load)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert "version" in payload
    assert "model" in payload


def test_analyze_returns_full_result(client: TestClient) -> None:
    r = client.post("/analyze", json={"text": "Bu ürün çok güzel"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["sentiment_label"] == "POZITIF"
    assert payload["sentiment_score"] == 0.85
    assert payload["text"] == "Bu ürün çok güzel"
    assert "overrides_applied" in payload


def test_analyze_critical_override_short_circuits(client: TestClient) -> None:
    r = client.post("/analyze", json={"text": "Polis çağırdılar"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["sentiment_label"] == "NEGATIF"
    assert payload["sentiment_score"] == -0.95
    assert any(o["layer"] == "critical" for o in payload["overrides_applied"])


def test_analyze_validation_empty_text(client: TestClient) -> None:
    r = client.post("/analyze", json={"text": ""})
    assert r.status_code == 422


def test_analyze_validation_extra_field(client: TestClient) -> None:
    r = client.post("/analyze", json={"text": "ok", "extra": "nope"})
    assert r.status_code == 422


def test_batch_endpoint_preserves_order(client: TestClient) -> None:
    r = client.post(
        "/analyze/batch",
        json={"texts": ["Çok güzel", "Polis", "Kötü ürün"]},
    )
    assert r.status_code == 200
    payload = r.json()
    assert len(payload) == 3
    assert payload[0]["sentiment_label"] == "POZITIF"
    assert payload[1]["sentiment_label"] == "NEGATIF"  # critical
    assert payload[2]["sentiment_label"] == "NEGATIF"  # bert


def test_batch_validation_empty_list(client: TestClient) -> None:
    r = client.post("/analyze/batch", json={"texts": []})
    assert r.status_code == 422


def test_metrics_endpoint(client: TestClient) -> None:
    sample = {
        "results": [
            {
                "text": "a", "sentiment_label": "POZITIF", "sentiment_score": 0.9,
                "overrides_applied": [], "company_perspective": "Lojistik / Kargo Firması Hatası",
            },
            {
                "text": "b", "sentiment_label": "NEGATIF", "sentiment_score": -0.95,
                "overrides_applied": [], "company_perspective": "Stok Yönetimi",
            },
            {
                "text": "c", "sentiment_label": "NEGATIF", "sentiment_score": -0.5,
                "overrides_applied": [], "company_perspective": "Stok Yönetimi",
            },
        ]
    }
    r = client.post("/metrics", json=sample)
    assert r.status_code == 200
    p = r.json()
    assert p["total"] == 3
    assert p["crisis_count"] == 1
    assert abs(p["negative_rate"] - (2 / 3)) < 1e-6
    assert p["alert"] is True
    # Top bottlenecks come back as list of [name, count]
    top = dict(p["top_bottlenecks"])
    assert top["Stok Yönetimi"] == 2


def test_metrics_endpoint_empty(client: TestClient) -> None:
    r = client.post("/metrics", json={"results": []})
    assert r.status_code == 422


def test_openapi_schema_available(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "/analyze" in schema["paths"]
    assert "/analyze/batch" in schema["paths"]
    assert "/metrics" in schema["paths"]
    assert "/health" in schema["paths"]
