# Strategic stats batch_id coverage audit — Sprint 9.2 E

**Date:** 2026-05-14
**Scope:** [packages/imga-api/src/imga_api/services/stats_aggregator.py](packages/imga-api/src/imga_api/services/stats_aggregator.py)
+ every method it dispatches to in
[analytics_service.py](packages/imga-api/src/imga_api/services/analytics_service.py)
+ the SWOT/OKR consumers.

## Method

`grep -n "batch_id\|batch_job_id" packages/imga-api/src/imga_api/services/stats_aggregator.py` plus a manual read of every aggregation surface the strategic report touches.

## Finding

Sprint 9.2 E ("strategic stats batch_id full coverage") was largely already delivered by Sprint 8.3.11 and Sprint 9.0.5-B H. Every aggregation in `StrategicStatsAggregator.collect(batch_id=...)` threads the same scope to its downstream call:

| Aggregation | Method | batch_id route |
|---|---|---|
| Headline | `compute_headline_metrics(batch_id=...)` | Sprint 9.0.5-B H — direct kwarg, WHERE `batch_job_id =` ([analytics_service.py:1220-1221](packages/imga-api/src/imga_api/services/analytics_service.py#L1220)) |
| NPS | `compute_nps_summary(batch_job_id=...)` | Direct kwarg, applied via `_apply_nps_window` |
| Monthly trend | `compute_monthly_nps_trend(...)` | Tenant-wide by design (12-month historical context); the strategy page header uses anchor date, not batch |
| Sentiment distribution | `sentiment_distribution(filters=...)` | Sprint 8.3.11 — `AnalyticsFilters.batch_job_id` woven through `_apply_review_filters` ([analytics_service.py:1231-1232](packages/imga-api/src/imga_api/services/analytics_service.py#L1231)) |
| Category distribution | `category_distribution(filters=...)` | Same `AnalyticsFilters` path |
| Company-perspective | `compute_company_perspective_distribution(filters=...)` | Same `AnalyticsFilters` path |

Downstream consumers:

| Consumer | Path |
|---|---|
| SWOT | `SwotService.generate(batch_id=...)` → `StatsAggregator.collect(batch_id=...)` ([swot_service.py:131-143](packages/imga-api/src/imga_api/services/swot_service.py#L131)) |
| OKR | Reads SWOT row's `input_stats` — inherits batch scope |
| Strategic reports route | POST body `batch_id` → `SwotService(batch_id=...)` ([tenant_strategic_reports.py:236](packages/imga-api/src/imga_api/routes/tenant_strategic_reports.py#L236)) |

## Action

No code change needed for the aggregation surface. Sprint 9.2 docs this audit as the verification step.

The remaining gap is the **action-extraction service** (`action_extraction_service.py`): when a batch-scoped SWOT generates action items via the LLM, the items themselves carry `source_report_id` (the SWOT) but not a direct `batch_job_id`. The SWOT row IS batch-scoped (via `input_stats.batch_id`), so traceability is one hop — the UI / audits can chain SWOT → batch — but a future sprint that wants action items directly filterable by batch can add a `source_batch_id` column. Logged here as a follow-up rather than blocking 9.2.

Frontend `/strategy` batch selector already drives the entire pipeline because the route's `batch_id` query parameter flows straight through to `SwotService.generate`. No additional plumbing needed.
