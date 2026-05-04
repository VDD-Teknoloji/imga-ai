"""WeasyPrint-backed renderer for SWOT + OKR strategic-report PDFs.

Sprint 8.3.6 / Alt-Faz 8.3.6.5.F. Service is pure rendering: takes a
``strategic_reports`` row's fields (the dict returned by SwotService /
OkrService.generate, or a freshly-fetched DB row), pumps it through
the matching Jinja2 template, hands the HTML to WeasyPrint, returns
the PDF bytes.

No DB, no auth, no I/O beyond reading the bundled HTML/CSS templates.
The route layer wraps it with auth + tenant-scoped fetching.

Templates live next to the service under ``templates/pdf/``. Inline
CSS is the WeasyPrint default — external stylesheet links work but
require disk-resolvable paths and add brittleness; for two reports
the duplication is a wash.

Türkçe glyph coverage: the Dockerfile installs ``fonts-dejavu-core``
+ ``fonts-liberation`` so the renderer can hit ı/ş/ğ/ç/Ö/Ü without
embedding fonts in the repo. Tests run on Alpine via the test compose
which already has those packs from the same Dockerfile path.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import UTC, datetime
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_logger = logging.getLogger(__name__)

# Resolve the templates dir relative to THIS file so the service works
# from any cwd (lifespan-bound services + ad-hoc scripts).
_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates" / "pdf"

_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)


class PdfRenderError(Exception):
    """Raised when the renderer can't produce a PDF — missing fields,
    WeasyPrint bombs on an unsupported CSS construct, etc. Route
    layer maps to 500 with a Türkçe error message."""


class PdfRenderService:
    """Stateless renderer. One instance per route handler is fine —
    Jinja env + WeasyPrint don't carry per-request state."""

    def render_swot(self, report: dict[str, Any]) -> bytes:
        """Render a SWOT report as a PDF blob.

        Expects the row shape SwotService.generate returns / the
        ``strategic_reports`` model serialises to:
        ``{id, report_type, date_from, date_to, output_payload,
        model_name, generation_duration_ms, ...}``.
        """
        if report.get("report_type") != "swot":
            raise PdfRenderError(
                f"render_swot called with report_type={report.get('report_type')!r}"
            )
        payload = report.get("output_payload") or {}
        return self._render_template(
            "swot.html",
            report=report,
            payload=payload,
            generated_at=datetime.now(UTC),
        )

    def render_okr(
        self, report: dict[str, Any], source_swot: dict[str, Any] | None = None
    ) -> bytes:
        """Render an OKR report as a PDF. ``source_swot`` is optional
        — when provided, the PDF includes a "based on the YYYY-MM-DD
        SWOT" footer reference."""
        if report.get("report_type") != "okr":
            raise PdfRenderError(
                f"render_okr called with report_type={report.get('report_type')!r}"
            )
        payload = report.get("output_payload") or {}
        return self._render_template(
            "okr.html",
            report=report,
            payload=payload,
            source_swot=source_swot,
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _render_template(template_name: str, **context: Any) -> bytes:
        """Common Jinja → WeasyPrint pipeline. Imports WeasyPrint
        lazily so test environments without the system libs (fonts/
        Pango) only fail on actual render attempts, not module
        import."""
        try:
            from weasyprint import HTML
        except ImportError as exc:  # pragma: no cover — runtime image guarantees this
            raise PdfRenderError(
                "WeasyPrint not available in this environment. "
                "Check Dockerfile system deps (libpango / libcairo)."
            ) from exc

        template = _jinja_env.get_template(template_name)
        html = template.render(**context)
        try:
            return bytes(HTML(string=html).write_pdf())
        except Exception as exc:
            raise PdfRenderError(
                f"WeasyPrint failed to render {template_name}: {exc}"
            ) from exc
