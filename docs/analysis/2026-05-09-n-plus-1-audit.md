# N+1 query audit — Sprint 9.1 F

**Date:** 2026-05-09
**Scope:** [/reviews](packages/imga-api/src/imga_api/routes/tenant_reviews.py),
[/insights](packages/imga-api/src/imga_api/routes/tenant_insights.py),
[/executive-briefings](packages/imga-api/src/imga_api/routes/tenant_executive_briefings.py),
[/strategy](packages/imga-api/src/imga_api/routes/tenant_strategic_reports.py),
[/action-items](packages/imga-api/src/imga_api/routes/tenant_action_items.py).

## Method

1. `grep -rn "relationship\|back_populates" packages/imga-db/src/imga_db/models` to find ORM-defined relationships that could lazy-load.
2. `grep -rn "for.*in.*:.*await.*execute" packages/imga-api/src` to find loops that issue per-iteration queries.
3. Read each hot endpoint's service method end-to-end, count `session.execute` / `session.get` / `session.scalars` calls per request.

## Finding

The codebase deliberately uses **zero SQLAlchemy `relationship()` definitions**. Every `Mapped[list[...]]` column on a model is a JSONB blob (`overrides_applied`, `kpi_changes`, `top_actions`, `match_taxonomy_codes`, etc.), not a relationship collection. Joins between tables are written as explicit `select(A, B).outerjoin(B, ...)` and decoded by the route layer — see [review_list_service.py:161-176](packages/imga-api/src/imga_api/services/review_list_service.py#L161-L176) for the canonical shape.

This makes the standard N+1 anti-pattern (lazy-load on a relationship inside a loop) **structurally impossible**. There's no `review.tags` accessor that would silently fire `SELECT * FROM tags WHERE review_id=?` per row.

## Per-endpoint query counts (steady-state)

| Endpoint | Steady-state SELECTs | Notes |
|---|---|---|
| `/tenants/me/reviews` | 2 (count + paginated rows w/ outerjoin to taxonomy) | [review_list_service.py:147,176](packages/imga-api/src/imga_api/services/review_list_service.py#L147) |
| `/tenants/me/insights` | 4 (cohort totals + per-period rollup + label resolve + category map) | All `IN (...)` batched. [cohort_analyzer.py:159,197,257](packages/imga-api/src/imga_api/services/cohort_analyzer.py#L159) |
| `/tenants/me/executive-briefings` | 2 (briefing row + linked action_items via `id = ANY(top_action_item_ids)`) | The action-item linkage is a single batch query, not a loop. |
| `/tenants/me/strategic-reports` | 1-2 (list = single SELECT; detail adds the action-item linkage) | No relationship traversal. |
| `/tenants/me/action-items` | 1 (list); 2 (detail = row + events) | Sprint 9.1 A's `/events` route adds one extra query for the timeline; the list itself stays single-SELECT. |

None of the inspected endpoints scale linearly with row count. A 100-row `/reviews` page issues the same 2 queries a 1-row page does.

## Locked in with tests

[`packages/imga-api/tests/test_query_counts.py`](packages/imga-api/tests/test_query_counts.py) (new) wraps each hot endpoint in a per-request `event.listen('before_cursor_execute')` counter and asserts the steady-state numbers above. Adding a new ORM relationship that lazy-loads inside a route handler will break these tests immediately rather than degrade gracefully into a slow request that ages on the dashboard.

## Future N+1 vectors

These DON'T apply today but would re-open the door:

- Adding `relationship()` to any model + lazy default → switch to `lazy="raise"` so a stray access blows up loud rather than fans out queries.
- Streaming response writers that fetch a related row per chunk (none today).
- Hand-written `for row in rows: do_something_with(await fetch(row.x))` patterns. Reviewer rule: any `for` loop with an `await` that hits the DB is a regression unless the surrounding query has already been batched.
