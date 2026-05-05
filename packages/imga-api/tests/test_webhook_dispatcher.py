"""Sprint 8.3.10 — webhook dispatcher unit tests.

Pure logic — no DB, no live HTTP. Verifies the Slack and Teams
payload shapes match the documented incoming-webhook contracts.
The HTTP path uses an injectable AsyncClient with a MockTransport
so the test never reaches a real Slack endpoint.
"""

from __future__ import annotations

import json

import httpx
import pytest

from imga_api.services.webhook_dispatcher import (
    SlaWebhookPayload,
    WebhookDispatcher,
    WebhookDispatchError,
)


def _payload(**overrides: object) -> SlaWebhookPayload:
    base = {
        "rule_name": "Yüksek öncelikli yanıt",
        "review_text": "Kargom 5 gündür gelmiyor.",
        "review_id": "rid-1234",
        "taxonomy_label": "Kargo",
        "elapsed_minutes": 60,
        "threshold_minutes": 30,
        "severity": "warning",
    }
    base.update(overrides)
    return SlaWebhookPayload(**base)  # type: ignore[arg-type]


def test_slack_body_shape_includes_all_fields() -> None:
    body = WebhookDispatcher._slack_body(_payload(), channel=None)
    assert body["text"].startswith("⚠️ SLA İhlali:")
    attachment = body["attachments"][0]
    assert attachment["color"] == "warning"
    titles = {f["title"] for f in attachment["fields"]}
    assert {"Yorum", "Kategori", "Geçen süre", "SLA eşiği"}.issubset(titles)
    # review_id is stamped in the footer for trace-back.
    assert "rid-1234" in attachment["footer"]


def test_slack_body_critical_severity_uses_danger_colour() -> None:
    body = WebhookDispatcher._slack_body(
        _payload(severity="critical"), channel=None
    )
    assert body["attachments"][0]["color"] == "danger"


def test_slack_body_optional_channel_passes_through() -> None:
    body = WebhookDispatcher._slack_body(_payload(), channel="#cx-alerts")
    assert body["channel"] == "#cx-alerts"


def test_teams_body_shape_uses_message_card_format() -> None:
    body = WebhookDispatcher._teams_body(_payload())
    assert body["@type"] == "MessageCard"
    assert body["@context"] == "https://schema.org/extensions"
    fact_names = {f["name"] for f in body["sections"][0]["facts"]}
    assert {"Kural", "Yorum", "Kategori"}.issubset(fact_names)


@pytest.mark.asyncio
async def test_dispatch_slack_posts_json_payload() -> None:
    """Inject a MockTransport AsyncClient and verify the dispatcher
    POSTs the Slack-shaped JSON to the supplied URL."""
    posted: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        posted.append(
            {
                "url": str(request.url),
                "json": json.loads(request.content),
            }
        )
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        dispatcher = WebhookDispatcher(client=client)
        await dispatcher.dispatch_slack(
            "https://hooks.slack.com/services/TEST",
            _payload(),
            channel="#cx",
        )

    assert len(posted) == 1
    assert posted[0]["url"] == "https://hooks.slack.com/services/TEST"
    body = posted[0]["json"]
    assert isinstance(body, dict)
    assert body["channel"] == "#cx"
    assert "attachments" in body


@pytest.mark.asyncio
async def test_dispatch_raises_on_non_2xx() -> None:
    """Slack/Teams returning 4xx/5xx must surface as
    WebhookDispatchError so the SLA engine catch path can swallow it."""

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server down")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        dispatcher = WebhookDispatcher(client=client)
        with pytest.raises(WebhookDispatchError, match="HTTP 500"):
            await dispatcher.dispatch_slack(
                "https://hooks.slack.com/services/TEST", _payload()
            )
