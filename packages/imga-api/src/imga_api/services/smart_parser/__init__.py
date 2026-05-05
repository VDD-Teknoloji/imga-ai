"""Smart column detection for upload preview.

Sprint 8.3.8. Set of detectors that scan a CSV/XLSX file's headers +
sample rows and propose which logical field each column carries
(review_text / nps_score / date / customer_id ship via the existing
imga-core parsers; Sprint 8.3.8 adds order_id / product_name /
customer_name / price / turkish_date — heavier signals that require
content inspection, not just header pattern match).

The orchestrator (``SmartColumnDetector``) runs every detector
against every column and resolves conflicts by confidence: each
column gets exactly one assigned field (the highest-scoring
detector); other detectors that fired on the same column surface as
``alternatives`` so the UI can offer the dropdown override.

All detectors are pure functions — given the same column name +
samples they return the same result. No DB, no I/O. Test compose
exercises them through a fake-file fixture.
"""

from __future__ import annotations

from imga_api.services.smart_parser.orchestrator import (
    DetectedColumn,
    PreviewResult,
    SmartColumnDetector,
)
from imga_api.services.smart_parser.types import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    DetectorResult,
    FieldName,
)

__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "DetectedColumn",
    "DetectorResult",
    "FieldName",
    "PreviewResult",
    "SmartColumnDetector",
]
