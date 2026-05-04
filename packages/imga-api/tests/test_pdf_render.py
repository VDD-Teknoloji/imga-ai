"""Sprint 8.3.6.5 — PdfRenderService unit tests.

No DB, no auth. Just the renderer ↔ template ↔ WeasyPrint pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from imga_api.services.pdf_render import PdfRenderError, PdfRenderService


def _swot_report(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "report_type": "swot",
        "date_from": "2026-01-01",
        "date_to": "2026-03-31",
        "model_name": "gemini-2.5-pro",
        "generation_duration_ms": 12345,
        "created_at": datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        "input_stats": {},
        "output_payload": {
            "strengths": [
                {"title": "Hızlı kargo", "description": "Müşteri memnun.", "evidence": "%30 pozitif"},
            ],
            "weaknesses": [
                {"title": "İade gecikmesi", "description": "Süreç uzun.", "evidence": "20 yorum"},
            ],
            "opportunities": [
                {"title": "Yeni pazar", "description": "Anadolu yayılım.", "evidence": "Bölge talep"},
            ],
            "threats": [
                {"title": "Rakip indirim", "description": "Pazar baskısı.", "evidence": "Sosyal medya"},
            ],
            "strategic_recommendations": [
                {
                    "title": "İade SLA",
                    "description": "5 günden 3 güne",
                    "priority": "yüksek",
                    "estimated_impact": "yüksek",
                },
            ],
        },
    }
    base.update(overrides)
    return base


def _okr_report(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "22222222-2222-2222-2222-222222222222",
        "report_type": "okr",
        "date_from": None,
        "date_to": None,
        "model_name": "gemini-2.5-pro",
        "generation_duration_ms": 8900,
        "created_at": datetime(2026, 4, 2, 10, 0, tzinfo=UTC),
        "input_stats": {},
        "output_payload": {
            "objectives": [
                {
                    "objective": "Müşteri memnuniyetini artır",
                    "rationale": "Zayıf yön: iade gecikmesi.",
                    "key_results": [
                        {"text": "NPS +10", "metric": "NPS", "baseline": "-15", "target": "-5"},
                    ],
                },
            ],
        },
    }
    base.update(overrides)
    return base


def _pdf_or_skip() -> PdfRenderService:
    """Build the renderer or skip the test if WeasyPrint isn't
    installed locally. Test compose has it; ad-hoc local dev may not."""
    try:
        import weasyprint  # noqa: F401
    except ImportError:
        pytest.skip("WeasyPrint not installed in this environment")
    return PdfRenderService()


def test_render_swot_returns_pdf_bytes_with_magic_header() -> None:
    """Smoke: PDF bytes start with the %PDF- magic header. WeasyPrint
    actually ran and produced a valid PDF stream."""
    renderer = _pdf_or_skip()
    pdf_bytes = renderer.render_swot(_swot_report())
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:5] == b"%PDF-"
    # Reasonable size — even a minimal one-page PDF clears 1 KB.
    assert len(pdf_bytes) > 1024


def test_render_okr_includes_source_swot_metadata_when_provided() -> None:
    """When source_swot is passed, the OKR PDF embeds a "Kaynak SWOT"
    block. We don't parse the PDF — just confirm the renderer accepts
    the second argument and produces a valid stream."""
    renderer = _pdf_or_skip()
    source = {
        "id": "11111111-1111-1111-1111-111111111111",
        "created_at": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
    }
    pdf_bytes = renderer.render_okr(_okr_report(), source)
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_swot_handles_empty_payload_gracefully() -> None:
    """A SWOT row whose output_payload has empty arrays still renders
    — the templates surface the "Madde yok." placeholder. WeasyPrint
    must not bomb on the empty for-loop branches."""
    renderer = _pdf_or_skip()
    report = _swot_report(
        output_payload={
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
            "strategic_recommendations": [],
        }
    )
    pdf_bytes = renderer.render_swot(report)
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_swot_rejects_wrong_report_type() -> None:
    """Defence-in-depth — calling render_swot with an OKR row is a
    bug at the route layer and must surface as PdfRenderError instead
    of producing a SWOT-shaped PDF off OKR data."""
    renderer = PdfRenderService()
    with pytest.raises(PdfRenderError, match="report_type"):
        renderer.render_swot(_okr_report())


def test_render_okr_accepts_source_swot_with_iso_string_datetime() -> None:
    """Sprint 8.3.6.6 round-6 regression — the route layer hands
    ``source_swot`` to the renderer as a Pydantic
    ``model_dump(mode='json')`` result, where ``created_at`` is an
    ISO string instead of a ``datetime``. Production crashed with
    ``UndefinedError: 'str object' has no attribute 'strftime'``;
    the renderer now hydrates the field before passing to Jinja."""
    renderer = _pdf_or_skip()
    source = {
        "id": "11111111-1111-1111-1111-111111111111",
        # ISO 8601 with offset — exactly the shape Pydantic emits.
        "created_at": "2026-03-01T09:00:00+00:00",
    }
    pdf_bytes = renderer.render_okr(_okr_report(), source)
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_okr_handles_source_swot_without_created_at() -> None:
    """Defensive: when source_swot omits ``created_at`` the template
    falls through to the "tarih belirsiz" branch via Jinja's
    truthiness guard. Renderer must not crash on the missing field."""
    renderer = _pdf_or_skip()
    source = {
        "id": "11111111-1111-1111-1111-111111111111",
        # created_at intentionally absent
    }
    pdf_bytes = renderer.render_okr(_okr_report(), source)
    assert pdf_bytes[:5] == b"%PDF-"
