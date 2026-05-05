"""Concrete detectors for the smart_parser package.

Sprint 8.3.8. Each detector module exports one class; the orchestrator
imports them from here so a new field type lives in exactly one
``detectors/<name>.py`` module + an entry in ``ALL_DETECTORS``.
"""

from __future__ import annotations

from imga_api.services.smart_parser.detectors.customer_name import (
    CustomerNameDetector,
)
from imga_api.services.smart_parser.detectors.order_id import OrderIdDetector
from imga_api.services.smart_parser.detectors.price import PriceDetector
from imga_api.services.smart_parser.detectors.product_name import (
    ProductNameDetector,
)
from imga_api.services.smart_parser.detectors.turkish_date import (
    TurkishDateDetector,
)

# Order is informational only; the orchestrator runs every detector
# against every column and ranks the results by confidence.
ALL_DETECTORS = (
    OrderIdDetector(),
    ProductNameDetector(),
    CustomerNameDetector(),
    PriceDetector(),
    TurkishDateDetector(),
)


__all__ = [
    "ALL_DETECTORS",
    "CustomerNameDetector",
    "OrderIdDetector",
    "PriceDetector",
    "ProductNameDetector",
    "TurkishDateDetector",
]
