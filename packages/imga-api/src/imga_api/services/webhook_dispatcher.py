"""Outbound webhook dispatcher for SLA action types.

Sprint 8.3.10. Sends incoming-webhook payloads to Slack / Teams when
a matching SLA rule fires. The action_config dict on sla_rules
carries the URL + optional channel override:

    {"webhook_url": "https://hooks.slack.com/services/...",
     "channel": "#cx-alerts"}        # optional, Slack-only

This sprint:
  * ``slack_webhook`` — live, Slack incoming-webhook format
  * ``teams_webhook`` — Teams MessageCard format

Errors are caught + logged with full traceback; the SLA evaluator
does NOT propagate webhook failures back to the user-facing route.
A network blip on Slack must not break review ingestion.

Test coverage uses respx (HTTPX mock) to assert payload shape
without hitting real webhooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

_logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


class WebhookDispatchError(Exception):
    """Raised when the webhook URL responds non-2xx OR times out.
    Caller logs + swallows; the user-facing path stays green."""


@dataclass(frozen=True)
class SlaWebhookPayload:
    """Domain payload the dispatcher serialises into Slack / Teams
    formats. Built by the SLA engine when a matching rule fires."""

    rule_name: str
    review_text: str
    review_id: str
    taxonomy_label: str | None
    elapsed_minutes: int | None
    threshold_minutes: int | None
    severity: str  # "warning" / "critical"


class WebhookDispatcher:
    """Stateless dispatcher. ``client`` is injectable for tests so a
    respx mock transport can intercept the POST."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def dispatch_slack(
        self,
        webhook_url: str,
        payload: SlaWebhookPayload,
        *,
        channel: str | None = None,
    ) -> None:
        body = self._slack_body(payload, channel=channel)
        await self._post(webhook_url, body, label="slack")

    async def dispatch_teams(
        self,
        webhook_url: str,
        payload: SlaWebhookPayload,
    ) -> None:
        body = self._teams_body(payload)
        await self._post(webhook_url, body, label="teams")

    async def _post(
        self, url: str, body: dict[str, Any], *, label: str
    ) -> None:
        client = self._client
        opened_locally = False
        try:
            if client is None:
                client = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
                opened_locally = True
            try:
                resp = await client.post(url, json=body)
                if not 200 <= resp.status_code < 300:
                    raise WebhookDispatchError(
                        f"{label} webhook returned HTTP {resp.status_code}"
                    )
            finally:
                if opened_locally and client is not None:
                    await client.aclose()
        except httpx.HTTPError as exc:
            _logger.exception(
                "%s webhook dispatch failed",
                label,
                extra={"url_host": _safe_host(url)},
            )
            raise WebhookDispatchError(
                f"{label} webhook network error: {exc}"
            ) from exc

    @staticmethod
    def _slack_body(
        payload: SlaWebhookPayload, *, channel: str | None
    ) -> dict[str, Any]:
        """Slack incoming-webhook attachment shape. ``danger`` colour
        for critical, ``warning`` for everything else."""
        colour = "danger" if payload.severity == "critical" else "warning"
        fields = [
            {
                "title": "Yorum",
                "value": _truncate(payload.review_text, 240),
                "short": False,
            },
        ]
        if payload.taxonomy_label:
            fields.append(
                {
                    "title": "Kategori",
                    "value": payload.taxonomy_label,
                    "short": True,
                }
            )
        if payload.elapsed_minutes is not None:
            fields.append(
                {
                    "title": "Geçen süre",
                    "value": f"{payload.elapsed_minutes} dk",
                    "short": True,
                }
            )
        if payload.threshold_minutes is not None:
            fields.append(
                {
                    "title": "SLA eşiği",
                    "value": f"{payload.threshold_minutes} dk",
                    "short": True,
                }
            )
        body: dict[str, Any] = {
            "text": f"⚠️ SLA İhlali: {payload.rule_name}",
            "attachments": [
                {
                    "color": colour,
                    "fields": fields,
                    "footer": f"review_id={payload.review_id}",
                }
            ],
        }
        if channel:
            body["channel"] = channel
        return body

    @staticmethod
    def _teams_body(payload: SlaWebhookPayload) -> dict[str, Any]:
        """Microsoft Teams MessageCard format. Compact — Teams
        wraps long text awkwardly."""
        theme = "FF0000" if payload.severity == "critical" else "FFA500"
        facts = [
            {"name": "Kural", "value": payload.rule_name},
            {"name": "Yorum", "value": _truncate(payload.review_text, 240)},
        ]
        if payload.taxonomy_label:
            facts.append({"name": "Kategori", "value": payload.taxonomy_label})
        if payload.elapsed_minutes is not None:
            facts.append(
                {"name": "Geçen süre", "value": f"{payload.elapsed_minutes} dk"}
            )
        if payload.threshold_minutes is not None:
            facts.append(
                {"name": "SLA eşiği", "value": f"{payload.threshold_minutes} dk"}
            )
        return {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "themeColor": theme,
            "summary": f"SLA İhlali: {payload.rule_name}",
            "sections": [
                {
                    "activityTitle": f"⚠️ SLA İhlali: {payload.rule_name}",
                    "facts": facts,
                }
            ],
        }


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _safe_host(url: str) -> str:
    """Extract the host so logs don't leak the secret webhook URL.
    Slack / Teams URLs encode the routing token in the path."""
    try:
        parsed = httpx.URL(url)
        return parsed.host
    except Exception:
        return "unknown"


__all__ = [
    "SlaWebhookPayload",
    "WebhookDispatchError",
    "WebhookDispatcher",
]
