"""Sprint 9.2 A — public metric registry endpoint.

Frontend reads this once at app load (or via the
``useMetricDefinitions`` hook) and caches the result. The payload
mirrors the seed data in Migration 0026 and the
``imga_core.metrics.METRIC_DEFINITIONS`` constant — those three
sources are the single contract for "what does NPS mean here, what
unit does it carry, what's its range".

Requires authentication (any role) but is tenant-agnostic — the
registry is the same for every tenant. The dependency is intentional:
unauthenticated probes don't need to enumerate the platform's KPIs.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from imga_core.metrics import list_metric_definitions
from pydantic import BaseModel

from imga_api.auth_deps import CurrentUser, get_current_user

router = APIRouter(prefix="/metrics", tags=["Metrics"])

_AnyAuthenticated = Depends(get_current_user)


class MetricDefinitionResponse(BaseModel):
    metric_key: str
    display_name: str
    description: str
    formula: str
    unit: str
    range_min: float | None
    range_max: float | None
    higher_is_better: bool
    aggregation: str


@router.get(
    "/definitions",
    response_model=list[MetricDefinitionResponse],
    summary="Public KPI metric registry. Tenant-agnostic.",
)
async def list_metrics(
    _current: Annotated[CurrentUser, _AnyAuthenticated],
) -> list[MetricDefinitionResponse]:
    """Returns every metric the platform reports, with display name,
    formula description, unit, range, and direction. The frontend
    binds metric chart axes / progress bars / tooltips to this
    payload so the UI never invents a label for a backend metric."""
    return [
        MetricDefinitionResponse(
            metric_key=m.metric_key,
            display_name=m.display_name,
            description=m.description,
            formula=m.formula,
            unit=m.unit,
            range_min=m.range_min,
            range_max=m.range_max,
            higher_is_better=m.higher_is_better,
            aggregation=m.aggregation,
        )
        for m in list_metric_definitions()
    ]
