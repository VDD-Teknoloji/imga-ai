# 2026-05-14 Batch Upload Audit — Production Smoke Notes

Sprint 9.5 A4. The batch upload happy path went through 9.0.5 (the
`succeeded_rows` / `failed_rows` accounting fix) and 9.4 (LLM-audit
savepoint isolation + dispatcher concurrency). This note is the
end-to-end smoke checklist an operator runs against a production
tenant after a fresh deploy. It is not a CI step — it intentionally
hits the live system to catch the kind of integration gaps that the
test compose can't see (CORS, cookie domain, Caddy headers, real LLM
key rotation, real Postgres + Redis latency).

## Pre-flight

- VPS deploy completed; web + api containers reporting healthy in
  `docker compose ps -f infra/imga/production/docker-compose.yml`.
- Caddy access log shows 200s on `/auth/me` for the operator.
- `alembic upgrade head` ran against `DATABASE_URL_OWNER` without
  errors (Sprint 9.5 added migration 0028 + 0029).
- At least one Gemini API key in the active tenant's
  `tenant_gemini_credentials` table; `status='active'`.

## The smoke run

1. **Login + tenant switch.** Open `app.imga.ai`, sign in as a tenant
   admin, switch into the target tenant. Confirm `/dashboard` paints
   without the "Aktif tenant yok" banner.
2. **Upload a known small file** (50–100 rows, single `yorum` column,
   include 1–2 Turkish reviews per crisis / positive / neutral
   sentiment range so the downstream NPS + crisis counts are
   non-trivial). The upload page is `/upload`.
3. **Watch the batch job page.** SSE stream should fire `progress`
   events every 5–10 rows. Sprint 9.0.5 made the SSE channel close
   on completion; if the bar sticks at 99% for >30s, that is a
   regression and a stop-the-line signal.
4. **Verify counts on completion.** `succeeded_rows + failed_rows ==
   total_rows`. If not, the dispatcher's row-accounting drift came
   back — check the `batch_jobs.error_summary` JSON.
5. **Open one of the analysed reviews.** Confirm `sentiment_label`,
   `primary_category`, `overrides_applied`. If `overrides_applied` is
   `null` for a row that contains a tier1 keyword (e.g. *"intihar"*,
   *"hesap çalındı"*), the keyword override layer is silent.
6. **Hit the dashboard.** Headline cards must reflect the batch's
   reviews — `total_reviews` increment matches the upload size. The
   Sprint 9.5 B4 wiring lets the headline accept `?batch_id=...`; the
   strategy page is the consumer once a SWOT is regenerated.
7. **Generate a SWOT scoped to the batch.** `/strategy` → "New SWOT" →
   pick the batch from the source dropdown. The first SWOT under
   gemini-2.5-pro (Sprint 9.5 A3 cutover) will take longer than the
   old flash baseline — expect ~30–60s end-to-end. Surface the
   timing in the run log so the next operator knows what "healthy"
   looks like.
8. **Check `llm_audit_log` rows for the run.** `prompt_tokens` +
   `completion_tokens` must be present (not NULL). NULL means the
   provider's structured-response path returned without usage_metadata
   — Sprint 9.4 F + 9.4.5 isolated audit failures from the main
   transaction; if every audit row is NULL the savepoint isolation
   may have regressed.

## What "green" looks like

The whole run, end to end, lands inside **15 minutes** for a
100-row batch. The dashboard reflects the new totals before the
operator finishes the SWOT step. No 500s in
`/var/log/imga-prod-api/access.log`. The SWOT response renders all
four quadrants + at least three `strategic_recommendations`.

## What "yellow" looks like

- 1–2 `failed_rows` in a 100-row run when the inputs are unrestricted
  customer text. Document the failing row's `error_summary` snippet;
  if it's a TR-specific tokeniser edge case, ticket it but don't
  block. The dispatcher is allowed soft failures.
- Headline NPS shows `Yeterli veri yok` when the upload had fewer
  than 5 NPS-bearing rows. Not a bug.

## What stops the line

- Any `succeeded_rows + failed_rows != total_rows` mismatch.
- `llm_audit_log` rows with `status='failed'` AND no `error_text`
  populated. The Sprint 9.4 audit-row guarantee is "every LLM call
  produces an audit row with usable error context."
- SSE channel returns 401 mid-stream (cookie expiry during a 30-min
  upload — a Sprint 9.4 G regression class). The 9.4.5 single-replay
  401-retry guard should refresh and resume; if it loops, escalate.
- SWOT response missing `strategic_recommendations` array. The
  ActionExtractionService (Sprint 9.5 B2) dedups on this content;
  empty input means the briefing schedule's downstream action-item
  extract will produce nothing.

## After the run

Note the batch_id + start/end timestamps + observed timings in
`docs/handoffs/` so the next operator has a baseline to diff
against. Audit smoke is only useful when prior runs are documented
— a 30s slowdown is invisible in isolation but obvious next to last
month's number.
