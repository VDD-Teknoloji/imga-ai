"""OKR generator orchestrator.

Sprint 8.3.6 / Alt-Faz 8.3.6.4. Variant of SwotService that turns one
SWOT report into one OKR report. Differences from SWOT (rationale in
the alt-faz prompt):

  * No Redis cache. The user can ask for multiple OKR drafts off the
    same SWOT and we want each one fresh — caching here would silently
    surface a stale draft.
  * Input is a SWOT row's ``output_payload`` (not a stats snapshot).
    The OkrService fetches the parent strategic_reports row, asserts
    ``report_type='swot'`` + tenant ownership, and feeds the payload
    into the OKR user prompt.
  * Persisted row carries ``source_report_id`` pointing at the parent
    SWOT, so the UI can render "based on the YYYY-MM SWOT" without
    a join trick.
  * Uses ``provider.generate_okr`` (temperature 0.3, max_output_tokens
    4096) instead of ``generate_swot``. The provider's per-method
    defaults handle the divergence.

Failure surface mirrors SwotService:

  * NoCredentialsError — no active rows. (Re-imported from
    llm_credentials so route layer handles it identically.)
  * SourceReportNotFoundError — UUID missing OR wrong report_type
    OR wrong tenant. RLS keeps us honest on tenant; the type guard is
    explicit because the route layer mustn't accept "OKR off another
    OKR" silently.
  * AllKeysExhaustedError — every key in rotation hit RateLimit /
    InvalidKey. Service stamps last_failed_at on the InvalidKey-marked
    rows before re-raising (same convention as SwotService).
  * OkrResponseInvalidError — defence-in-depth schema check.
  * Other LLMError — propagates unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from imga_core.llm import (
    AllKeysExhaustedError,
    GeminiKeyRotator,
    InvalidKeyError,
    LLMError,
)
from imga_core.llm.gemini import GeminiProvider
from imga_db.models import StrategicReport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.llm.prompts.okr_v1 import (
    OKR_RESPONSE_SCHEMA,
    OKR_SYSTEM_PROMPT,
    render_okr_user_prompt,
)
from imga_api.services.llm_credentials import (
    NoCredentialsError,
    load_active_gemini_keys,
    mark_keys_failed,
)
from imga_api.services.strategic_constants import (
    company_size_label,
    industry_label,
)

_logger = logging.getLogger(__name__)

# Sprint 9.5.4 — Gemini 3 cutover alongside briefing / swot. See
# executive_briefing_service.py for the full 2.5 504 → 2.0 404 →
# 3-flash-preview history; OKR generation tracks the same model
# choice for cost + behavior parity across strategy surfaces.
DEFAULT_MODEL_NAME = "gemini-3-flash-preview"


class OkrServiceError(Exception):
    """Base for OKR generator failures the route layer must map to
    HTTP responses."""


class SourceReportNotFoundError(OkrServiceError):
    """The supplied source_report_id doesn't resolve to a SWOT row
    owned by the active tenant. Route layer surfaces 404. Covers
    three cases under one exception class because they're
    indistinguishable from the route's perspective: missing UUID,
    wrong report_type (e.g. another OKR), and cross-tenant access
    (RLS hides it as missing)."""


class OkrResponseInvalidError(OkrServiceError):
    """LLM returned a 200 that's syntactically JSON but missing the
    schema's top-level ``objectives`` field. Same defence-in-depth
    role SWOT's validation plays."""


class OkrService:
    """Orchestrate one OKR generation off a SWOT source row."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID | None,
        *,
        provider: GeminiProvider | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._provider = provider or _build_provider_without_key()

    async def generate(self, source_report_id: UUID) -> dict[str, Any]:
        """Generate one OKR row off ``source_report_id`` (must be a
        SWOT report owned by the active tenant).

        Returns the persisted row as a serialisable dict (same shape
        SwotService.generate uses)."""
        # 1. Source SWOT — fetch + ownership/type guard.
        source = await self._load_source_swot(source_report_id)

        # 2. Credentials → rotator. Same path as SwotService; shared
        # helper means the "no creds" UI flow is identical.
        keys = await load_active_gemini_keys(self._session, self._tenant_id)
        if not keys:
            raise NoCredentialsError(
                "Tenant has no active LLM API keys configured"
            )
        rotator = GeminiKeyRotator(keys)

        # 3. Render the OKR user prompt from the SWOT payload + the
        # tenant context the SWOT input_stats already snapshotted.
        from imga_api.services.prompt_override import select_prompt

        _ctx = self._render_context(source)
        selection = await select_prompt(
            self._session,
            tenant_id=self._tenant_id,
            template_key="okr",
            variables=_ctx,
            default_system_prompt=OKR_SYSTEM_PROMPT,
            default_user_prompt=lambda: render_okr_user_prompt(_ctx),
        )
        user_prompt = selection.user_prompt

        # 4. LLM call with rotation.
        failed_invalid_key_ids: list[UUID] = []

        async def _call(api_key: str) -> tuple[dict[str, Any], dict[str, int] | None]:
            try:
                return await self._provider.generate_okr(
                    api_key=api_key,
                    system_prompt=selection.system_prompt,
                    user_prompt=user_prompt,
                    response_schema=OKR_RESPONSE_SCHEMA,
                )
            except InvalidKeyError:
                for k in keys:
                    if k.value == api_key:
                        failed_invalid_key_ids.append(UUID(k.id))
                        break
                raise

        # Sprint 9.5.6 — LLM call governance audit. Mirrors the SWOT
        # service's wrap (which mirrors the briefing service's, see
        # there for the full deferred-raise rationale). Pre-9.5.6
        # OKR generation never wrote an llm_call_audit row, so the
        # 504-storm we hit during the gemini-3-flash-preview cutover
        # was invisible on /admin/llm-audit for both SWOT and OKR.
        from imga_api.services.llm_audit_service import (
            CALL_TYPE_OKR,
            LLMCallAuditor,
            LLMCallContext,
        )

        audit_ctx = LLMCallContext(
            tenant_id=self._tenant_id,
            call_type=CALL_TYPE_OKR,
            model_name=DEFAULT_MODEL_NAME,
            model_provider="gemini",
            prompt_template_key="okr",
            prompt_template_version="v1",
            actor_user_id=self._user_id,
            related_entity_type="strategic_report",
            related_entity_id=source.id,
        )
        auditor = LLMCallAuditor(self._session, audit_ctx, prompt=user_prompt)
        start = time.monotonic()
        token_usage: dict[str, int] | None = None
        try:
            async with auditor:
                try:
                    (response, token_usage), key_used = (
                        await rotator.call_with_rotation(_call)
                    )
                except AllKeysExhaustedError as exc:
                    auditor.record_failure(
                        error_type="all_keys_exhausted",
                        error_message=str(exc.__cause__ or exc)[:1024],
                    )
                    raise
                except LLMError as exc:
                    auditor.record_failure(
                        error_type="api_error",
                        error_message=str(exc)[:1024],
                    )
                    raise
                except Exception as exc:
                    auditor.record_failure(
                        error_type="other",
                        error_message=f"{type(exc).__name__}: {exc}"[:1024],
                    )
                    raise
                auditor.record_success(
                    input_tokens=(
                        token_usage.get("input") if token_usage else None
                    ),
                    output_tokens=(
                        token_usage.get("output") if token_usage else None
                    ),
                )
        except AllKeysExhaustedError:
            await mark_keys_failed(self._session, failed_invalid_key_ids)
            raise
        except LLMError:
            raise

        duration_ms = int((time.monotonic() - start) * 1000)

        if failed_invalid_key_ids:
            await mark_keys_failed(self._session, failed_invalid_key_ids)

        # 5. Validate.
        self._validate_okr_response(response)

        # 6. Persist with the parent SWOT's id in source_report_id.
        report_dict = await self._persist_report(
            response=response,
            source=source,
            model_name=DEFAULT_MODEL_NAME,
            duration_ms=duration_ms,
            token_usage=token_usage,
        )

        _logger.info(
            "OKR generated tenant=%s source_swot=%s key_id=%s key_label=%s duration_ms=%d",
            self._tenant_id, source.id, key_used.id, key_used.label, duration_ms,
        )
        return report_dict

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_source_swot(
        self, source_report_id: UUID
    ) -> StrategicReport:
        """Fetch + assert the source row is a SWOT for THIS tenant.

        RLS already restricts to tenant-owned rows; the explicit
        tenant_id check is defence in depth. The report_type check
        is mandatory — the route must reject "OKR off another OKR"
        with a 404, not silently chain reports.
        """
        stmt = (
            select(StrategicReport)
            .where(StrategicReport.id == source_report_id)
            .where(StrategicReport.tenant_id == self._tenant_id)
            .where(StrategicReport.report_type == "swot")
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise SourceReportNotFoundError(
                f"SWOT report {source_report_id} not found for tenant"
            )
        return row

    @staticmethod
    def _render_context(source: StrategicReport) -> dict[str, Any]:
        """Build the dict the OKR user prompt template expects.

        Uses the source SWOT's ``output_payload`` for the four SWOT
        sections + recommendations, and its ``input_stats`` for the
        tenant-context fields the SWOT generator already captured. The
        OKR generator deliberately does NOT re-fetch tenant context —
        it should produce OKRs anchored on the SAME context the SWOT
        was produced under, even if the user has since edited their
        /settings/profile.
        """
        payload = source.output_payload
        stats = source.input_stats
        return {
            "strengths": payload.get("strengths", []),
            "weaknesses": payload.get("weaknesses", []),
            "opportunities": payload.get("opportunities", []),
            "threats": payload.get("threats", []),
            "strategic_recommendations": payload.get(
                "strategic_recommendations", []
            ),
            "industry_label": industry_label(
                stats.get("industry"), stats.get("industry_other_text")
            ),
            "company_size_label": company_size_label(stats.get("company_size")),
        }

    @staticmethod
    def _validate_okr_response(payload: dict[str, Any]) -> None:
        """Two-layer validation, mirroring SwotService:

          * **Top-level required (strict):** missing ``objectives``
            means the row is unrenderable; reject.
          * **Per-objective counts (permissive):** the 2-4 / 2-4 spec
            used to live in the response_schema as ``minItems`` /
            ``maxItems`` until the Gemini SDK crashed on those keys
            (8.3.6.6 round-1 production). It now lives in the system
            prompt + this soft check: out-of-range counts log a
            warning but the row gets persisted regardless.
        """
        required = OKR_RESPONSE_SCHEMA["required"]
        missing = [k for k in required if k not in payload]
        if missing:
            raise OkrResponseInvalidError(
                f"OKR response missing required fields: {missing}"
            )

        objectives = payload.get("objectives", [])
        if not (2 <= len(objectives) <= 4):
            _logger.warning(
                "OKR response has %d objectives, expected 2-4 — "
                "persisting anyway",
                len(objectives),
            )
        for idx, obj in enumerate(objectives):
            krs = obj.get("key_results", []) if isinstance(obj, dict) else []
            if not (2 <= len(krs) <= 4):
                _logger.warning(
                    "OKR objective[%d] has %d key_results, expected 2-4 — "
                    "persisting anyway",
                    idx, len(krs),
                )

    async def _persist_report(
        self,
        *,
        response: dict[str, Any],
        source: StrategicReport,
        model_name: str,
        duration_ms: int,
        token_usage: dict[str, int] | None,
    ) -> dict[str, Any]:
        report = StrategicReport(
            tenant_id=self._tenant_id,
            report_type="okr",
            # OKR inherits the SWOT's date window — the strategic
            # picture is the same period; UI can show "OKRs based on
            # the 2026-Q1 SWOT" without separate filters.
            date_from=source.date_from,
            date_to=source.date_to,
            # input_stats here mirrors what we fed the LLM (SWOT's own
            # input_stats snapshot). Storing it again means the OKR
            # row is fully self-describing — the UI can render the
            # OKR detail without back-walking source_report_id.
            input_stats=dict(source.input_stats),
            output_payload=response,
            source_report_id=source.id,
            model_name=model_name,
            token_usage=token_usage,
            generation_duration_ms=duration_ms,
            created_by_user_id=self._user_id,
        )
        self._session.add(report)
        await self._session.flush()
        report_id = report.id
        return {
            "id": str(report_id),
            "tenant_id": str(self._tenant_id),
            "report_type": "okr",
            "date_from": (
                source.date_from.isoformat() if source.date_from else None
            ),
            "date_to": (
                source.date_to.isoformat() if source.date_to else None
            ),
            "input_stats": dict(source.input_stats),
            "output_payload": response,
            "source_report_id": str(source.id),
            "model_name": model_name,
            "token_usage": token_usage,
            "generation_duration_ms": duration_ms,
            "created_by_user_id": (
                str(self._user_id) if self._user_id is not None else None
            ),
        }


def _build_provider_without_key() -> GeminiProvider:
    """Same trick as SwotService — placeholder constructor key, every
    actual call passes a real per-attempt key via the rotator."""
    return GeminiProvider(api_key="x", model_name=DEFAULT_MODEL_NAME)


__all__ = [
    "DEFAULT_MODEL_NAME",
    "OkrResponseInvalidError",
    "OkrService",
    "OkrServiceError",
    "SourceReportNotFoundError",
]
