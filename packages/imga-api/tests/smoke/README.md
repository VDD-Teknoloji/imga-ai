# Post-deploy smoke tests

Sprint 9.4 J — gated regression suite for the three Sprint 9.4 P1
fixes (period mapping, KPI window, dimension propagation). The
default test compose skips this directory; an operator runs the
suite explicitly after a deploy via the `smoke` compose profile.

## Running

The smoke suite is bundled into a dedicated image stage
(`smoke-runtime`) and exposed as the `api-smoke` service under
the `smoke` compose profile on both production and staging.
Default `compose up -d` does NOT start it.

```bash
# Staging (the canonical place to run this).
cd /opt/imga/infra/imga/staging
sudo docker compose --profile smoke run --rm api-smoke

# Production (only with a healthy backup — the suite seeds + tears
# down its own tenants, but the safety belt is yours).
cd /opt/imga/infra/imga/production
sudo docker compose --profile smoke run --rm api-smoke
```

Exit code 0 = green, non-zero = at least one scenario failed.
The container is `--rm`-ed on exit so a re-run rebuilds from a
clean slate.

## Why a separate image stage

The production `runtime` stage is deliberately minimal — pytest +
the tests/ tree are not shipped to the api / api-worker
containers. `smoke-runtime` derives from `runtime` and layers on:

- `pytest` + `pytest-asyncio`
- `packages/imga-api/tests/` (conftest + the smoke suite)
- `RUN_SMOKE=1` env so `pytest.mark.skipif` releases the suite
- `pyproject.toml` for the pytest config block
- CMD overridden to run the suite once and exit

This keeps the production image surface area unchanged for
operational deploys; the smoke image is only built when an
operator explicitly invokes the `smoke` profile.

## Scenarios

- **Senaryo 2** — scheduled briefing period mapping (Sprint 9.4 A):
  a `weekly`/`monthly` schedule maps to `week`/`month` before
  reaching `ExecutiveBriefingService.generate`.
- **Senaryo 3** — KPI goal progress reads the *period* window
  (Sprint 9.4 B): 10 in-window promoters + 90 out-of-window
  detractors → positive NPS, not the all-time average.
- **Senaryo 5** — batch upload populates dimension columns
  (Sprint 9.4 D): the file parser fills `customer_tier` when
  the tenant has a CSV mapping configured.

Pre-9.4 the smoke story was "open the page, declare victory" —
that missed three demo-blocker bugs because none of them
surfaced in the UI. The pattern here — "assert the row landed
in the DB with the right value" — is the failure mode the smoke
story was missing.
