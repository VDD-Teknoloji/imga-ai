"""SmartColumnDetector — runs every detector against every column and
resolves conflicts by confidence.

Sprint 8.3.8. Each column ends up with one assigned field (the
highest-scoring detector's verdict); other detectors that fired on
the same column show up as ``alternatives`` so the UI dropdown can
offer "this is actually X" without re-running detection.

The orchestrator is the public API of the smart_parser package; it
lives here (not in ``__init__.py``) so the tests can construct it
directly with a custom detector list when needed.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from imga_api.services.smart_parser.base import Detector
from imga_api.services.smart_parser.detectors import ALL_DETECTORS
from imga_api.services.smart_parser.types import DetectorResult, FieldName

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectedColumn:
    """One column's resolved verdict.

    Attributes:
        column_name: original header.
        field_name: best-confidence detector's field, or ``None`` if
            no detector fired (the UI surfaces those as "Yoksay
            önerisi" by default).
        confidence: best-confidence value, in [0, 1].
        sample_values: first 3 non-empty cells.
        alternatives: other detectors' results sorted by confidence
            descending. Lets the dropdown show "or it could be …".
        metadata: best-detector's metadata (locale / format /
            is_pii / etc.). PII surfaces here as ``is_pii=True``.
    """

    column_name: str
    field_name: FieldName | None
    confidence: float
    sample_values: list[str]
    alternatives: list[DetectorResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreviewResult:
    """Top-level preview payload returned by the API.

    ``pii_warnings`` is a flat list of strings (e.g.
    ``"customer_name:musteri_adi"``) the UI shows in a banner — the
    user must check the consent box before the upload proceeds.
    """

    headers: list[str]
    row_count: int
    detected: list[DetectedColumn]
    pii_warnings: list[str] = field(default_factory=list)


class SmartColumnDetector:
    """Orchestrates the detector ensemble over a sampled file."""

    def __init__(
        self, detectors: Sequence[Detector] | None = None
    ) -> None:
        self._detectors: tuple[Detector, ...] = tuple(
            detectors if detectors is not None else ALL_DETECTORS
        )

    def detect(
        self,
        headers: list[str],
        samples: dict[str, list[str]],
        row_count: int,
    ) -> PreviewResult:
        """Run every detector against every column.

        Args:
            headers: original header strings, in file order.
            samples: per-column sample values (typically the first
                ~50-100 rows), keyed by the original header.
            row_count: total data-row count from the file.
        """
        detected: list[DetectedColumn] = []
        pii_warnings: list[str] = []

        for header in headers:
            sample_values = samples.get(header, [])
            results: list[DetectorResult] = []
            for detector in self._detectors:
                try:
                    result = detector.detect(header, sample_values, headers)
                except Exception:
                    _logger.exception(
                        "smart_parser detector raised — skipping",
                        extra={
                            "detector": type(detector).__name__,
                            "column": header,
                        },
                    )
                    continue
                if result is not None:
                    results.append(result)

            results.sort(key=lambda r: r.confidence, reverse=True)
            best = results[0] if results else None

            if best is None:
                detected.append(
                    DetectedColumn(
                        column_name=header,
                        field_name=None,
                        confidence=0.0,
                        sample_values=_first_samples(sample_values),
                        alternatives=[],
                        metadata={},
                    )
                )
                continue

            if best.metadata.get("is_pii"):
                pii_warnings.append(f"{best.field_name.value}:{header}")

            detected.append(
                DetectedColumn(
                    column_name=header,
                    field_name=best.field_name,
                    confidence=best.confidence,
                    sample_values=best.sample_values,
                    alternatives=results[1:],
                    metadata=dict(best.metadata),
                )
            )

        return PreviewResult(
            headers=headers,
            row_count=row_count,
            detected=detected,
            pii_warnings=pii_warnings,
        )


def _first_samples(values: list[str], limit: int = 3) -> list[str]:
    out: list[str] = []
    for v in values:
        s = (v or "").strip()
        if not s:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out
