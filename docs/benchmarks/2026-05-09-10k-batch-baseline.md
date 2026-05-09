# 10K-row batch baseline — Sprint 9.1 G

**Date:** 2026-05-09 (skeleton — fill in after first run)
**Sprint:** 9.1 G
**Hardware:** TBD (operator fills: CPU model, RAM, container limits)
**Database:** PostgreSQL 17 (test compose) / production-grade (live)
**API build:** TBD (`git rev-parse HEAD` after push)

This document records the first 10K-row baseline so future regression
tests have something to compare against. Sprint 9.0.5-A's optimisations
were validated up to 2,852 rows; the 10K target is the demo's worst-case
upload size.

## Run procedure

```bash
cd packages/imga-api
RUN_BENCHMARK=1 IMGA_BENCHMARK_LIVE_GEMINI=1 \
  pytest tests/test_10k_benchmark.py -s
```

Flag interactions:
* `RUN_BENCHMARK=1` alone → stub-Gemini run (BERT + DB only)
* `+ IMGA_BENCHMARK_LIVE_GEMINI=1` → live Gemini, multi-key rotator,
  expects production-shaped tenant_llm_credentials seed in the test
  database.

While the run is in flight, server-agent collects from the host:
* `py-spy dump --pid <api-worker-pid>` x3 spaced 30s apart
* `/proc/<api-worker-pid>/status` peak `VmRSS`
* `journalctl -u imga-api -f | grep "batch chunk"` (Sprint 9.1 E
  structured logs)
* Postgres: `SELECT pg_database_size('imga')` before/after
* Slack/Teams webhook log (live mode only) for SLA dispatch volume

## Fill-in template

```
=== 10K BATCH BENCHMARK ===
  total_rows         = 10000
  duration_sec       = TBD
  throughput_rows_s  = TBD
  mode               = stub|live
===========================
```

| Metric | Stub mode | Live mode |
|---|---|---|
| Wall-clock (s) | TBD | TBD |
| Throughput (rows/s) | TBD | TBD |
| BERT total (s) | TBD | TBD |
| DB write total (s) | TBD | TBD |
| LLM fallback rows | 0 (stub) | TBD |
| 504 occurrences | 0 (stub) | TBD |
| Circuit-breaker activations | 0 | TBD |
| Memory peak (MB) | TBD | TBD |
| Tickets created | TBD | TBD |
| Duplicates skipped | TBD | TBD |

## Expected ballpark (informational)

Sprint 9.0.5-A optimisations + Sprint 9.0.5-A R7 retry/timeout work
suggest:

* **Stub mode**: 10K rows ≈ 5 min on the dev machine (BERT-bound).
* **Live mode, clean Gemini**: 10K rows ≈ 25-30 min with concurrency
  8 + chunk_size 200. Sustained ~6-7 rows/s.
* **Live mode, pathological 504 storm**: bounded by R7's circuit
  breaker — should still complete (with elevated `requires_manual_review`
  rows on circuit-open windows) within the 60-minute timeout.

## Regression triggers

Future runs that compare against this baseline should investigate
when:
* Throughput drops > 30% in stub mode → BERT path regression
  (transformers upgrade, classifier change, lock contention).
* Throughput drops > 50% in live mode → Gemini SDK path regression
  (the 9.1 H google-genai migration is the obvious suspect).
* Memory peak > 2× baseline → leak (Sprint 9.0.5-A R7 fix may have
  regressed under the new SDK).
* 504 rate > 5% with reasonable rate-limits → key-rotator misbehaving.

## History

* 2026-05-09 — skeleton landed alongside Sprint 9.1 push (cdc296c+).
  First numbers TBD.
